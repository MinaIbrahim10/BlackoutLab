"""Authored toy commerce services. No external payments, infrastructure or shell tools."""
import uuid
import time
from .telemetry import build_tracer, operation

INITIAL_STOCK = 20
UNIT_PRICE = 2500  # integer pretend cents
FAULTS = {'orders':{'drop-order'},'payments':{'payments-down'},'inventory':{'duplicate-reservation'}}


class DomainError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def validate_order(key, qty, amount):
    if not isinstance(key,str) or not 1 <= len(key) <= 80:
        raise DomainError('Invalid idempotency key',422)
    if type(qty) is not int or not 1 <= qty <= 5 or type(amount) is not int or amount != qty*UNIT_PRICE:
        raise DomainError('Invalid quantity or amount',422)


class Service:
    def __init__(self, role, store, transport=None):
        self.role, self.store, self.transport = role, store, transport
        self.tracer,self.provider = build_tracer(role)

    def fault(self, run, name, enabled):
        if name not in FAULTS[self.role]:
            raise DomainError('Fault is not valid for this service',422)
        if type(enabled) is not bool: raise DomainError('enabled must be a boolean',422)
        self.store.set_fault(run,name,enabled)
        return {'fault':name,'enabled':enabled}

    def snapshot(self, run):
        tables = {'orders':['intents','orders'],'payments':['payments'],'inventory':['inventory','reservations']}[self.role]
        result = {t:self.store.rows(t,run) for t in tables}
        result['faults'] = {f:self.store.fault(run,f) for f in FAULTS[self.role]}
        if self.role == 'inventory' and not result['inventory']:
            result['inventory'] = [{'run':run,'stock':INITIAL_STOCK}]
        return result

    def call(self, action, run, payload=None, correlation=None):
        payload = payload or {}
        if action == 'snapshot': return self.snapshot(run)
        if action == 'events': return self.store.events(run,payload.get('after',0))
        with operation(self.store,self.tracer,run,self.role,action,correlation) as corr:
            if action == 'snapshot': return self.snapshot(run)
            if action == 'events': return self.store.events(run,payload.get('after',0))
            if action == 'fault': return self.fault(run,payload['name'],payload['enabled'])
            if self.role == 'payments' and action == 'capture': return self.capture(run,**payload)
            if self.role == 'inventory' and action == 'reserve': return self.reserve(run,**payload)
            if self.role == 'inventory' and action == 'deduplicate': return self.deduplicate(run)
            if self.role == 'orders' and action == 'checkout': return self.checkout(run,corr,**payload)
            if self.role == 'orders' and action == 'retry-pending': return self.retry_pending(run,corr)
            raise DomainError('Unsupported operation',404)

    def capture(self, run, key, qty, amount):
        validate_order(key,qty,amount)
        if self.store.fault(run,'payments-down'):
            raise DomainError('Payment service unavailable (injected fault)',503)
        with self.store.connect(write=True) as c:
            row = c.execute('SELECT * FROM payments WHERE run=? AND key=?',(run,key)).fetchone()
            if row:
                if (row['qty'],row['amount']) != (qty,amount):
                    raise DomainError('Idempotency payload conflict')
                return {'key':key,'captured':True,'deduplicated':True}
            c.execute('INSERT INTO payments VALUES(?,?,?,?,?)',(run,key,amount,qty,time.time()))
        self.store.log(run,'payments','payment.captured',{'key':key,'amount':amount})
        return {'key':key,'captured':True,'deduplicated':False}

    def reserve(self, run, key, qty):
        validate_order(key,qty,qty*UNIT_PRICE)
        duplicate = self.store.fault(run,'duplicate-reservation')
        with self.store.connect(write=True) as c:
            c.execute('INSERT OR IGNORE INTO inventory VALUES(?,?)',(run,INITIAL_STOCK))
            row = c.execute('SELECT qty FROM reservations WHERE run=? AND key=?',(run,key)).fetchone()
            if row and row['qty'] != qty:
                raise DomainError('Idempotency payload conflict')
            if row and not duplicate:
                return {'key':key,'reserved':True,'deduplicated':True}
            stock = c.execute('SELECT stock FROM inventory WHERE run=?',(run,)).fetchone()['stock']
            if stock < qty:
                raise DomainError('Insufficient inventory')
            c.execute('UPDATE inventory SET stock=stock-? WHERE run=?',(qty,run))
            c.execute('INSERT INTO reservations VALUES(?,?,?,?)',(uuid.uuid4().hex,run,key,qty))
        self.store.log(run,'inventory','inventory.reserved',{'key':key,'qty':qty,'idempotency_bypassed':duplicate})
        return {'key':key,'reserved':True,'deduplicated':False}

    def deduplicate(self, run):
        removed = restored = 0
        with self.store.connect(write=True) as c:
            rows = c.execute('SELECT * FROM reservations WHERE run=? ORDER BY rowid',(run,)).fetchall()
            seen = set()
            for row in rows:
                if row['key'] in seen:
                    c.execute('DELETE FROM reservations WHERE id=?',(row['id'],))
                    removed += 1
                    restored += row['qty']
                seen.add(row['key'])
            c.execute('UPDATE inventory SET stock=stock+? WHERE run=?',(restored,run))
        self.store.log(run,'inventory','inventory.deduplicated',{'removed':removed,'restored':restored})
        return {'removed':removed,'restored':restored}

    def checkout(self, run, correlation, key, qty, amount):
        validate_order(key,qty,amount)
        # Durable intent precedes the cross-service saga. Repeated calls converge by key.
        with self.store.connect(write=True) as c:
            row = c.execute('SELECT * FROM intents WHERE run=? AND key=?',(run,key)).fetchone()
            if row and (row['qty'],row['amount']) != (qty,amount):
                raise DomainError('Idempotency payload conflict')
            c.execute('INSERT OR IGNORE INTO intents VALUES(?,?,?,?)',(run,key,qty,amount))
            existing = c.execute('SELECT * FROM orders WHERE run=? AND key=?',(run,key)).fetchone()
            if existing:
                return {'key':key,'committed':True,'deduplicated':True}
        self.transport.call('payments','capture',run,{'key':key,'qty':qty,'amount':amount},correlation)
        if self.store.fault(run,'drop-order'):
            raise DomainError('Order writer failed after payment capture (injected fault)',503)
        self.transport.call('inventory','reserve',run,{'key':key,'qty':qty},correlation)
        with self.store.connect(write=True) as c:
            c.execute('INSERT OR IGNORE INTO orders VALUES(?,?,?,?,?)',(run,key,qty,amount,time.time()))
        self.store.log(run,'orders','order.committed',{'key':key,'qty':qty,'amount':amount},correlation)
        return {'key':key,'committed':True,'deduplicated':False}

    def retry_pending(self, run, correlation):
        intents = self.store.rows('intents',run)
        completed = []
        for intent in intents:
            self.checkout(run,correlation,**{k:intent[k] for k in ('key','qty','amount')})
            completed.append(intent['key'])
        return {'replayed':completed}
