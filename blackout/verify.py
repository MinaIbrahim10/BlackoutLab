"""Independent accounting checks. Narrative confidence never determines recovery."""
from collections import Counter
from .services import INITIAL_STOCK


def snapshot(transport, run):
    return {role:transport.call(role,'snapshot',run) for role in ('orders','payments','inventory')}


def verify(state):
    orders = {x['key']:x for x in state['orders']['orders']}
    intents = {x['key']:x for x in state['orders']['intents']}
    payments = {x['key']:x for x in state['payments']['payments']}
    reservations = state['inventory']['reservations']
    counts = Counter(x['key'] for x in reservations)
    reserved_qty = Counter()
    for row in reservations: reserved_qty[row['key']] += row['qty']
    checks = []
    def check(name, ok, details): checks.append({'name':name,'passed':bool(ok),'details':details})
    check('all_intents_committed',set(intents)==set(orders),{'pending':sorted(set(intents)-set(orders))})
    check('payments_match_orders',set(payments)==set(orders) and all(payments[k]['amount']==o['amount'] and payments[k]['qty']==o['qty'] for k,o in orders.items() if k in payments),
          {'orphaned_payments':sorted(set(payments)-set(orders)),'unpaid_orders':sorted(set(orders)-set(payments))})
    check('one_reservation_per_order',set(counts)==set(orders) and all(counts[k]==1 and reserved_qty[k]==o['qty'] for k,o in orders.items()),
          {'reservations_per_key':dict(counts),'quantity_per_key':dict(reserved_qty)})
    stock = state['inventory']['inventory'][0]['stock']
    expected = INITIAL_STOCK-sum(o['qty'] for o in orders.values())
    check('stock_matches_committed_orders',stock==expected,{'actual':stock,'expected':expected})
    check('stock_ledger_conserved',stock+sum(x['qty'] for x in reservations)==INITIAL_STOCK,{'stock':stock,'reserved':sum(x['qty'] for x in reservations)})
    check('faults_disabled',not any(v for s in state.values() for v in s['faults'].values()),{})
    return {'healthy':all(c['passed'] for c in checks),'checks':checks,
            'orders':len(orders),'payments':len(payments),'stock':stock}
