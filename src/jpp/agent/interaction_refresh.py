"""Turn a remembered lead into an interaction when perception confirms it."""


def refresh_interaction(target, objects):
    if not target.get('reobserve_interaction'):
        return
    obj = objects.get(target['id'])
    if not obj or not obj.get('visible') or obj.get('map') != target.get('map'):
        return
    from .object_memory import RESOLVED_OUTCOMES
    if obj.get('outcome') in RESOLVED_OUTCOMES:
        return
    target.update(kind='talk', reobserve_interaction=False,
                  category=obj.get('category', 'unknown'),
                  label='Investigate the observed object',
                  completion='Dialogue observed and closed')
