"""Native Grafana presentation helpers; preserve operational query semantics."""
from copy import deepcopy

def panels(dashboard):

    def walk(items):
        for panel in items:
            yield panel
            yield from walk(panel.get('panels', []))
    return list(walk(dashboard.get('panels', [])))

def semantic_signature(dashboard):
    """All non-presentational query, variable, aggregation and threshold settings."""
    return {'uid': dashboard.get('uid'), 'title': dashboard.get('title'), 'templating': dashboard.get('templating'), 'time': dashboard.get('time'), 'panels': [{'id': p.get('id'), 'targets': p.get('targets'), 'datasource': p.get('datasource'), 'gridPos': p.get('gridPos'), 'transformations': p.get('transformations'), 'repeat': p.get('repeat'), 'reduceOptions': p.get('options', {}).get('reduceOptions'), 'defaults': {k: v for k, v in p.get('fieldConfig', {}).get('defaults', {}).items() if k in ['unit', 'min', 'max', 'mappings', 'thresholds', 'color']}} for p in panels(dashboard)]}

def style_dashboard(source):
    result = deepcopy(source)
    result['graphTooltip'] = 1
    for panel in panels(result):
        kind = panel.get('type')
        if kind == 'row':
            continue
        options = panel.setdefault('options', {})
        panel['transparent'] = kind == 'text'
        if kind == 'timeseries':
            custom = panel.setdefault('fieldConfig', {}).setdefault('defaults', {}).setdefault('custom', {})
            if custom.get('drawStyle', 'line') == 'line':
                custom.update({'lineInterpolation': 'smooth', 'lineWidth': 2, 'fillOpacity': 18, 'gradientMode': 'opacity', 'showPoints': 'never'})
            custom.update({'axisBorderShow': False})
            options.setdefault('legend', {}).update({'displayMode': 'table', 'placement': 'bottom', 'showLegend': True, 'calcs': ['lastNotNull', 'max']})
            options.setdefault('tooltip', {}).update({'mode': 'multi', 'sort': 'desc'})
        elif kind == 'stat':
            options.update({'colorMode': 'background', 'orientation': 'auto', 'textMode': 'value_and_name', 'wideLayout': True, 'text': {'titleSize': 13, 'valueSize': 26}})
        elif kind == 'gauge':
            options.update({'showThresholdMarkers': True, 'showThresholdLabels': False, 'text': {'titleSize': 13, 'valueSize': 22}})
        elif kind == 'heatmap':
            options['cellGap'] = 1
            options.setdefault('legend', {})['show'] = True
            options.setdefault('tooltip', {})['show'] = True
        elif kind == 'state-timeline':
            options.update({'rowHeight': 0.75, 'showValue': 'auto'})
            options.setdefault('tooltip', {}).update({'mode': 'multi', 'sort': 'desc'})
        elif kind == 'table':
            options.update({'showHeader': True, 'cellHeight': 'md'})
        elif kind == 'piechart':
            options['pieType'] = 'donut'
            options.setdefault('legend', {}).update({'displayMode': 'table', 'placement': 'bottom', 'showLegend': True, 'values': ['value', 'percent']})
    assert semantic_signature(source) == semantic_signature(result)
    return result
