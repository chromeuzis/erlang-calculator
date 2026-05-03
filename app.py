from flask import Flask, render_template, jsonify, request
import math

app = Flask(__name__)

NORMS = {
    'model_b': {
        'gos': [
            {'max': 0.01, 'label': 'Отлично (≤1%)', 'class': 'excellent',
             'description': 'Городские телефонные сети, магистральные каналы'},
            {'max': 0.02, 'label': 'Хорошо (≤2%)', 'class': 'good',
             'description': 'Ведомственные сети, бизнес-телефония'},
            {'max': 0.05, 'label': 'Приемлемо (≤5%)', 'class': 'acceptable',
             'description': 'Внутренние сети предприятий, офисные АТС'},
            {'max': 0.10, 'label': 'Посредственно (≤10%)', 'class': 'poor',
             'description': 'Резервные каналы, сельская связь'},
            {'max': 0.20, 'label': 'Плохо (≤20%)', 'class': 'bad',
             'description': 'Сети с низкими требованиями к качеству'}
        ],
        'utilization': [
            {'min': 0, 'max': 60, 'label': 'Недогрузка (<60%)', 'class': 'warning',
             'description': 'Избыток каналов, неоправданные затраты'},
            {'min': 60, 'max': 85, 'label': 'Оптимально (60-85%)', 'class': 'excellent',
             'description': 'Хороший баланс качества и затрат'},
            {'min': 85, 'max': 100, 'label': 'Перегрузка (>85%)', 'class': 'poor',
             'description': 'Высокий риск блокировок при всплесках трафика'}
        ]
    },
    'model_c': {
        'service_level': [
            {'min': 0.90, 'max': 1.0, 'label': 'Отлично (≥90%)', 'class': 'excellent',
             'description': 'Премиальные колл-центры, банки, страхование'},
            {'min': 0.80, 'max': 0.90, 'label': 'Хорошо (≥80%)', 'class': 'good',
             'description': 'Стандарт индустрии (правило 80/20)'},
            {'min': 0.70, 'max': 0.80, 'label': 'Приемлемо (≥70%)', 'class': 'acceptable',
             'description': 'Внутренняя техподдержка, справочные службы'},
            {'min': 0, 'max': 0.70, 'label': 'Низкий (<70%)', 'class': 'poor',
             'description': 'Требуется增加 операторов'}
        ],
        'avg_wait': [
            {'min': 0, 'max': 10, 'label': 'Отлично (<10 сек)', 'class': 'excellent',
             'description': 'Премиум-сервис, VIP-поддержка'},
            {'min': 10, 'max': 20, 'label': 'Хорошо (<20 сек)', 'class': 'good',
             'description': 'Стандартное время ожидания'},
            {'min': 20, 'max': 60, 'label': 'Приемлемо (<60 сек)', 'class': 'acceptable',
             'description': 'Некритичные службы, госучреждения'},
            {'min': 60, 'max': float('inf'), 'label': 'Долго (>60 сек)', 'class': 'poor',
             'description': 'Высокий риск потери клиентов'}
        ],
        'utilization': [
            {'min': 0, 'max': 70, 'label': 'Низкая (<70%)', 'class': 'warning',
             'description': 'Операторы простаивают, избыток персонала'},
            {'min': 70, 'max': 90, 'label': 'Оптимально (70-90%)', 'class': 'excellent',
             'description': 'Эффективная работа, есть резерв'},
            {'min': 90, 'max': 100, 'label': 'Высокая (>90%)', 'class': 'poor',
             'description': 'Риск выгорания персонала, нет резерва'}
        ]
    }
}


def evaluate(value, norms):
    """Оценивает значение по шкале норм"""
    for norm in norms:
        if 'max' in norm and 'min' in norm:
            if norm['min'] <= value <= norm['max']:
                return norm
        elif 'max' in norm:
            if value <= norm['max']:
                return norm
        elif 'min' in norm:
            if value >= norm['min']:
                return norm
    return norms[-1]


class ErlangCalculator:
    @staticmethod
    def erlang_b(servers, traffic):
        if traffic <= 0:
            return 0.0
        if servers <= 0:
            return 1.0
        if traffic >= servers * 10:
            return 1.0

        sum_series = 1.0
        term = 1.0
        try:
            for i in range(1, int(servers) + 1):
                term = term * traffic / i
                if term > 1e100:
                    return 1.0
                sum_series += term
            if sum_series > 1e100:
                return 1.0
            return term / sum_series
        except (OverflowError, ZeroDivisionError):
            return 1.0

    @staticmethod
    def find_servers_from_gos(traffic, target_gos, max_servers=10000):
        if traffic <= 0:
            return 0
        if target_gos <= 0:
            return max_servers
        if target_gos >= 1:
            return 1

        min_servers = max(1, int(math.ceil(traffic)))
        for n in range(min_servers, max_servers + 1):
            gos = ErlangCalculator.erlang_b(n, traffic)
            if gos <= target_gos:
                return n
        return max_servers

    @staticmethod
    def find_traffic_from_gos(servers, target_gos, max_traffic=100000):
        if servers <= 0:
            return 0.0
        if target_gos <= 0:
            return float(servers)
        if target_gos >= 1:
            return 0.0

        low = 0.0
        high = float(servers * 10)
        for _ in range(100):
            mid = (low + high) / 2
            gos = ErlangCalculator.erlang_b(servers, mid)
            if abs(gos - target_gos) < 1e-10:
                return mid
            elif gos < target_gos:
                low = mid
            else:
                high = mid
        return (low + high) / 2

    @staticmethod
    def erlang_c(servers, traffic):
        if traffic <= 0:
            return 0.0
        if servers <= 0:
            return 1.0
        if traffic >= servers:
            return 1.0
        eb = ErlangCalculator.erlang_b(servers, traffic)
        denominator = servers - traffic * (1 - eb)
        if denominator <= 0:
            return 1.0
        return (servers * eb) / denominator

    @staticmethod
    def average_wait_time(servers, traffic, avg_call_duration):
        if traffic >= servers:
            return float('inf')
        ec = ErlangCalculator.erlang_c(servers, traffic)
        if ec == 0:
            return 0
        return (ec * avg_call_duration) / (servers - traffic)

    @staticmethod
    def service_level(servers, traffic, avg_call_duration, target_time):
        if traffic >= servers:
            return 0.0
        ec = ErlangCalculator.erlang_c(servers, traffic)
        if ec == 0:
            return 1.0
        exp_term = math.exp(-(servers - traffic) * target_time / avg_call_duration)
        return 1 - ec * exp_term

    @staticmethod
    def find_servers_c(traffic, target_sl, avg_call_duration, target_time, max_servers=10000):
        servers = max(1, int(math.ceil(traffic)))
        while servers <= max_servers:
            if traffic >= servers:
                servers += 1
                continue
            sl = ErlangCalculator.service_level(servers, traffic, avg_call_duration, target_time)
            if sl >= target_sl:
                return servers
            servers += 1
        return max_servers

    @staticmethod
    def erlang_a(traffic, servers, patience_factor, recall_percent=0.0):
        if traffic <= 0:
            return 0.0
        if servers <= 0:
            return 1.0
        new_traffic = traffic
        for _ in range(100):
            gos = ErlangCalculator.erlang_b(servers, new_traffic)
            if patience_factor < 100:
                patience_effect = math.exp(-patience_factor)
                gos = min(1.0, gos + (1 - gos) * (1 - patience_effect))
            recall_factor = 1 - (gos * recall_percent)
            if recall_factor <= 0:
                return 1.0
            adjusted = traffic / recall_factor
            if abs(adjusted - new_traffic) < 1e-8:
                break
            new_traffic = adjusted
        return ErlangCalculator.erlang_b(servers, new_traffic)


calculator = ErlangCalculator()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/norms')
def get_norms():
    return jsonify(NORMS)


@app.route('/api/model_b/direct', methods=['POST'])
def model_b_direct():
    try:
        data = request.json
        traffic = float(data.get('traffic', 0))
        servers = int(data.get('servers', 0))
        if traffic < 0.01 or servers < 1:
            return jsonify({'success': False, 'error': 'Некорректные значения'}), 400

        gos = calculator.erlang_b(servers, traffic)
        carried_traffic = traffic * (1 - gos)
        blocked_traffic = traffic * gos
        utilization = (carried_traffic / servers * 100) if servers > 0 else 0

        gos_eval = evaluate(gos, NORMS['model_b']['gos'])
        util_eval = evaluate(utilization, NORMS['model_b']['utilization'])

        return jsonify({
            'success': True,
            'gos': gos, 'gos_percent': gos * 100,
            'carried_traffic': carried_traffic,
            'blocked_traffic': blocked_traffic,
            'utilization': utilization,
            'gos_norm': gos_eval,
            'utilization_norm': util_eval
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/model_b/inverse_servers', methods=['POST'])
def model_b_inverse_servers():
    try:
        data = request.json
        traffic = float(data.get('traffic', 0))
        target_gos = float(data.get('target_gos', 0.01))
        if traffic < 0.01 or target_gos < 0.01 or target_gos > 0.5:
            return jsonify({'success': False, 'error': 'Некорректные значения'}), 400

        servers = calculator.find_servers_from_gos(traffic, target_gos)
        actual_gos = calculator.erlang_b(servers, traffic)
        carried_traffic = traffic * (1 - actual_gos)
        utilization = (carried_traffic / servers * 100) if servers > 0 else 0

        gos_eval = evaluate(actual_gos, NORMS['model_b']['gos'])
        util_eval = evaluate(utilization, NORMS['model_b']['utilization'])

        return jsonify({
            'success': True,
            'servers': servers,
            'actual_gos': actual_gos,
            'actual_gos_percent': actual_gos * 100,
            'target_gos_percent': target_gos * 100,
            'carried_traffic': carried_traffic,
            'utilization': utilization,
            'gos_norm': gos_eval,
            'utilization_norm': util_eval
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/model_b/inverse_traffic', methods=['POST'])
def model_b_inverse_traffic():
    try:
        data = request.json
        servers = int(data.get('servers', 0))
        target_gos = float(data.get('target_gos', 0.01))
        if servers < 1 or target_gos < 0.01 or target_gos > 0.5:
            return jsonify({'success': False, 'error': 'Некорректные значения'}), 400

        traffic = calculator.find_traffic_from_gos(servers, target_gos)
        actual_gos = calculator.erlang_b(servers, traffic)
        carried_traffic = traffic * (1 - actual_gos)
        utilization = (carried_traffic / servers * 100) if servers > 0 else 0

        gos_eval = evaluate(actual_gos, NORMS['model_b']['gos'])
        util_eval = evaluate(utilization, NORMS['model_b']['utilization'])

        return jsonify({
            'success': True,
            'traffic': traffic,
            'actual_gos': actual_gos,
            'actual_gos_percent': actual_gos * 100,
            'target_gos_percent': target_gos * 100,
            'carried_traffic': carried_traffic,
            'utilization': utilization,
            'gos_norm': gos_eval,
            'utilization_norm': util_eval
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/model_c/direct', methods=['POST'])
def model_c_direct():
    try:
        data = request.json
        traffic = float(data.get('traffic', 0))
        servers = int(data.get('servers', 0))
        avg_duration = float(data.get('avg_duration', 180))
        target_time = float(data.get('target_time', 20))
        if traffic < 0.01 or servers < 1:
            return jsonify({'success': False, 'error': 'Некорректные значения'}), 400

        if traffic >= servers:
            return jsonify({
                'success': True,
                'warning': 'Нагрузка превышает число операторов! Система перегружена.',
                'ec': 1.0, 'ec_percent': 100.0,
                'avg_wait': float('inf'),
                'service_level': 0.0, 'service_level_percent': 0.0,
                'queue_length': float('inf'),
                'utilization': 100.0,
                'sl_norm': NORMS['model_c']['service_level'][-1],
                'wait_norm': NORMS['model_c']['avg_wait'][-1],
                'util_norm': NORMS['model_c']['utilization'][-1]
            })

        ec = calculator.erlang_c(servers, traffic)
        avg_wait = calculator.average_wait_time(servers, traffic, avg_duration)
        sl = calculator.service_level(servers, traffic, avg_duration, target_time)
        queue_length = (traffic * ec) / (servers - traffic) if ec > 0 else 0
        utilization = (traffic / servers * 100)

        sl_eval = evaluate(sl, NORMS['model_c']['service_level'])
        wait_eval = evaluate(avg_wait, NORMS['model_c']['avg_wait'])
        util_eval = evaluate(utilization, NORMS['model_c']['utilization'])

        return jsonify({
            'success': True,
            'ec': ec, 'ec_percent': ec * 100,
            'avg_wait': avg_wait,
            'service_level': sl, 'service_level_percent': sl * 100,
            'queue_length': queue_length,
            'utilization': utilization,
            'sl_norm': sl_eval,
            'wait_norm': wait_eval,
            'util_norm': util_eval
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/model_c/inverse', methods=['POST'])
def model_c_inverse():
    try:
        data = request.json
        traffic = float(data.get('traffic', 0))
        target_sl = float(data.get('target_sl', 0.8))
        avg_duration = float(data.get('avg_duration', 180))
        target_time = float(data.get('target_time', 20))
        if traffic < 0.01 or target_sl < 0.5 or target_sl > 0.99:
            return jsonify({'success': False, 'error': 'Некорректные значения'}), 400

        servers = calculator.find_servers_c(traffic, target_sl, avg_duration, target_time)
        ec = calculator.erlang_c(servers, traffic)
        sl = calculator.service_level(servers, traffic, avg_duration, target_time)
        avg_wait = calculator.average_wait_time(servers, traffic, avg_duration)
        utilization = (traffic / servers * 100)

        sl_eval = evaluate(sl, NORMS['model_c']['service_level'])
        wait_eval = evaluate(avg_wait, NORMS['model_c']['avg_wait'])
        util_eval = evaluate(utilization, NORMS['model_c']['utilization'])

        return jsonify({
            'success': True,
            'servers': servers,
            'ec': ec, 'ec_percent': ec * 100,
            'service_level': sl, 'service_level_percent': sl * 100,
            'target_sl_percent': target_sl * 100,
            'avg_wait': avg_wait,
            'queue_length': (traffic * ec) / (servers - traffic) if ec > 0 else 0,
            'utilization': utilization,
            'sl_norm': sl_eval,
            'wait_norm': wait_eval,
            'util_norm': util_eval
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/model_a/direct', methods=['POST'])
def model_a_direct():
    try:
        data = request.json
        traffic = float(data.get('traffic', 0))
        servers = int(data.get('servers', 0))
        patience = float(data.get('patience', 5))
        recall = float(data.get('recall', 0.1))
        if traffic < 0.01 or servers < 1:
            return jsonify({'success': False, 'error': 'Некорректные значения'}), 400

        gos_a = calculator.erlang_a(traffic, servers, patience, recall)
        gos_b = calculator.erlang_b(servers, traffic)
        effective_traffic = traffic / (1 - gos_a * recall) if gos_a * recall < 1 else float('inf')
        abandoned = gos_a * (1 - math.exp(-patience)) if patience < 100 else 0

        gos_eval = evaluate(gos_a, NORMS['model_b']['gos'])

        return jsonify({
            'success': True,
            'gos_a': gos_a, 'gos_a_percent': gos_a * 100,
            'gos_b': gos_b, 'gos_b_percent': gos_b * 100,
            'difference': abs(gos_a - gos_b),
            'difference_percent': abs(gos_a - gos_b) * 100,
            'effective_traffic': effective_traffic,
            'abandoned_calls': abandoned,
            'abandoned_percent': abandoned * 100,
            'gos_norm': gos_eval
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/graph/gos_vs_traffic', methods=['POST'])
def graph_gos_vs_traffic():
    data = request.json
    servers = int(data.get('servers', 50))
    model = data.get('model', 'B')
    max_traffic = servers * 1.5
    traffic_range = [i * max_traffic / 60 for i in range(0, 61)]
    datasets = []
    colors = {'B': '#4361ee', 'C': '#059669', 'A': '#dc2626'}
    names = {'B': 'Модель B', 'C': 'Модель C', 'A': 'Модель A'}

    models = ['B', 'C', 'A'] if model == 'ALL' else [model]
    for m in models:
        if m == 'B':
            vals = [calculator.erlang_b(servers, t) for t in traffic_range]
        elif m == 'C':
            vals = [calculator.erlang_c(servers, t) if t < servers else 1.0 for t in traffic_range]
        else:
            vals = [calculator.erlang_a(t, servers, 5, 0.1) for t in traffic_range]
        datasets.append({
            'label': f'{names[m]} (N={servers})',
            'data': vals,
            'borderColor': colors[m],
            'backgroundColor': colors[m] + '15',
            'borderWidth': 3, 'fill': True, 'tension': 0.4, 'pointRadius': 0
        })

    datasets.append({
        'label': 'Отлично (1%)',
        'data': [0.01] * len(traffic_range),
        'borderColor': '#22c55e', 'borderWidth': 1.5, 'borderDash': [5, 5],
        'fill': False, 'pointRadius': 0
    })
    return jsonify({'traffic': traffic_range, 'datasets': datasets, 'servers': servers})


@app.route('/api/graph/gos_vs_servers', methods=['POST'])
def graph_gos_vs_servers():
    data = request.json
    traffic = float(data.get('traffic', 50))
    model = data.get('model', 'B')
    min_servers = max(1, int(math.ceil(traffic * 0.5)))
    max_servers = int(traffic * 2)
    servers_range = list(range(min_servers, max_servers + 1))
    datasets = []
    colors = {'B': '#4361ee', 'C': '#059669', 'A': '#dc2626'}
    names = {'B': 'Модель B', 'C': 'Модель C', 'A': 'Модель A'}

    models = ['B', 'C', 'A'] if model == 'ALL' else [model]
    for m in models:
        if m == 'B':
            vals = [calculator.erlang_b(n, traffic) for n in servers_range]
        elif m == 'C':
            vals = [calculator.erlang_c(n, traffic) if traffic < n else 1.0 for n in servers_range]
        else:
            vals = [calculator.erlang_a(traffic, n, 5, 0.1) for n in servers_range]
        datasets.append({
            'label': f'{names[m]} (A={traffic})',
            'data': vals,
            'borderColor': colors[m],
            'backgroundColor': colors[m] + '15',
            'borderWidth': 3, 'fill': True, 'tension': 0.4, 'pointRadius': 0
        })

    datasets.append({
        'label': 'Отлично (1%)',
        'data': [0.01] * len(servers_range),
        'borderColor': '#22c55e', 'borderWidth': 1.5, 'borderDash': [5, 5],
        'fill': False, 'pointRadius': 0
    })
    return jsonify({'servers': servers_range, 'datasets': datasets, 'traffic': traffic})


@app.route('/api/graph/servers_vs_traffic', methods=['POST'])
def graph_servers_vs_traffic():
    data = request.json
    model = data.get('model', 'B')
    traffic_range = list(range(1, 101))
    gos_levels = [
        {'value': 0.01, 'label': 'GoS = 1% (отлично)', 'color': '#22c55e'},
        {'value': 0.02, 'label': 'GoS = 2% (хорошо)', 'color': '#3b82f6'},
        {'value': 0.05, 'label': 'GoS = 5% (приемлемо)', 'color': '#f59e0b'},
        {'value': 0.10, 'label': 'GoS = 10%', 'color': '#ef4444'}
    ]
    datasets = []
    for gl in gos_levels:
        vals = []
        for t in traffic_range:
            if model == 'B':
                vals.append(calculator.find_servers_from_gos(t, gl['value']))
            else:
                vals.append(calculator.find_servers_c(t, gl['value'], 180, 20))
        datasets.append({
            'label': gl['label'], 'data': vals,
            'borderColor': gl['color'], 'backgroundColor': 'transparent',
            'borderWidth': 2.5, 'fill': False, 'tension': 0.3, 'pointRadius': 0
        })
    datasets.append({
        'label': 'N = A (минимум)', 'data': traffic_range,
        'borderColor': '#94a3b8', 'borderWidth': 1.5, 'borderDash': [3, 3],
        'fill': False, 'pointRadius': 0
    })
    return jsonify({'traffic': traffic_range, 'datasets': datasets})


@app.route('/api/graph/sl_vs_traffic', methods=['POST'])
def graph_sl_vs_traffic():
    data = request.json
    servers = int(data.get('servers', 50))
    avg_duration = float(data.get('avg_duration', 180))
    max_traffic = servers * 0.95
    traffic_range = [i * max_traffic / 50 for i in range(0, 51)]
    target_times = [10, 20, 30, 60]
    colors = ['#4361ee', '#059669', '#f59e0b', '#dc2626']
    datasets = []
    for i, tt in enumerate(target_times):
        vals = [calculator.service_level(servers, t, avg_duration, tt) if t < servers else 0 for t in traffic_range]
        datasets.append({
            'label': f'Время ответа ≤ {tt} сек', 'data': vals,
            'borderColor': colors[i], 'backgroundColor': 'transparent',
            'borderWidth': 2.5, 'fill': False, 'tension': 0.4, 'pointRadius': 0
        })
    return jsonify({'traffic': traffic_range, 'datasets': datasets})


@app.route('/api/graph/comparison', methods=['POST'])
def graph_comparison():
    data = request.json
    servers = int(data.get('servers', 50))
    max_traffic = servers * 1.2
    traffic_range = [i * max_traffic / 60 for i in range(0, 61)]
    gos_b = [calculator.erlang_b(servers, t) for t in traffic_range]
    gos_c = [calculator.erlang_c(servers, t) if t < servers else 1.0 for t in traffic_range]
    utilization = [min(100, (t / servers) * 100) for t in traffic_range]
    datasets = [
        {
            'label': 'Блокировка (Модель B)', 'data': [v * 100 for v in gos_b],
            'borderColor': '#4361ee', 'backgroundColor': 'rgba(67,97,238,0.1)',
            'borderWidth': 2.5, 'fill': True, 'tension': 0.4, 'yAxisID': 'y', 'pointRadius': 0
        },
        {
            'label': 'Ожидание (Модель C)', 'data': [v * 100 for v in gos_c],
            'borderColor': '#059669', 'backgroundColor': 'rgba(5,150,105,0.1)',
            'borderWidth': 2.5, 'fill': True, 'tension': 0.4, 'yAxisID': 'y', 'pointRadius': 0
        },
        {
            'label': 'Использование (%)', 'data': utilization,
            'borderColor': '#f59e0b', 'borderWidth': 2.5, 'borderDash': [8, 4],
            'fill': False, 'tension': 0.4, 'yAxisID': 'y1', 'pointRadius': 0
        }
    ]
    return jsonify({'traffic': traffic_range, 'datasets': datasets, 'servers': servers})


@app.route('/api/table_data', methods=['POST'])
def table_data():
    data = request.json
    max_traffic = float(data.get('max_traffic', 20))
    step = float(data.get('step', 2))
    model = data.get('model', 'B')
    traffic_values = [round(i * step, 1) for i in range(1, int(max_traffic / step) + 1)]
    servers_range = range(1, int(max_traffic * 1.5) + 1)
    table = []
    for servers in servers_range:
        row = {'servers': servers, 'values': []}
        for traffic in traffic_values:
            if model == 'B':
                gos = calculator.erlang_b(servers, traffic)
            elif model == 'C':
                gos = calculator.erlang_c(servers, traffic) if traffic < servers else 1.0
            else:
                gos = calculator.erlang_a(traffic, servers, 5, 0.1)
            row['values'].append({'traffic': traffic, 'gos': gos, 'gos_percent': gos * 100})
        table.append(row)
    return jsonify({'traffic_values': traffic_values, 'table': table})
if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
