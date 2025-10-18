from flask import Flask, render_template, jsonify
import json
import requests
from collections import Counter
import psutil
import os

stats_data = {}
cpu_ram_data = []

def get_bot_process():
    """Find the bot process (main.py) by name."""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and 'main.py' in ' '.join(cmdline):
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None

app = Flask(__name__)

@app.route('/')
def dashboard():
    try:
        response = requests.get("http://localhost:8080/bot_stats", timeout=2)
        if response.status_code == 200:
            bot_data = response.json()
            sizes_data = [{"label": k, "value": v} for k, v in bot_data.get('server_size_breakdown', {}).items()]
            try:
                with open('message_counts.json', 'r') as f:
                    message_counts = json.load(f)
                messages_data = [{"label": guild_id, "value": count} for guild_id, count in message_counts.items()]
            except:
                messages_data = []
        else:
            sizes_data = [{"label": k, "value": v} for k, v in {}.items()]
            messages_data = []
    except requests.RequestException:
        sizes_data = [{"label": k, "value": v} for k, v in {}.items()]
        messages_data = []
    try:
        versions_data = [{"label": k, "value": v} for k, v in Counter({}).items()]
    except TypeError:
        versions_data = []
    cpu_percent = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    ram_percent = ram.percent
    ram_total = ram.total / (1024 ** 3)  
    ram_used = ram.used / (1024 ** 3)   
    ram_free = ram.available / (1024 ** 3)  

    process = psutil.Process()
    cpu_process = process.cpu_percent(interval=1)
    ram_process = process.memory_info().rss / (1024 ** 2)
    ram_process_percent = (ram_process / 1024) / ram_total * 100

    # Get bot process specs
    bot_process = get_bot_process()
    if bot_process:
        try:
            bot_cpu_process = bot_process.cpu_percent(interval=1)
            bot_ram_process = bot_process.memory_info().rss / (1024 ** 2)
            bot_ram_process_percent = (bot_ram_process / 1024) / ram_total * 100
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            bot_cpu_process = 0
            bot_ram_process = 0
            bot_ram_process_percent = 0
    else:
        bot_cpu_process = 0
        bot_ram_process = 0
        bot_ram_process_percent = 0

    cpu_pie_data = [
        {"label": "Process", "value": cpu_process},
        {"label": "System", "value": cpu_percent - cpu_process},
        {"label": "Free", "value": 100 - cpu_percent}
    ]
    ram_pie_data = [
        {"label": "Process", "value": ram_process_percent},
        {"label": "System", "value": ram_percent - ram_process_percent},
        {"label": "Free", "value": 100 - ram_percent}
    ]
    stats_data['sizes_data'] = sizes_data
    stats_data['versions_data'] = versions_data
    stats_data['messages_data'] = messages_data
    stats_data['cpu_pie_data'] = cpu_pie_data
    stats_data['ram_pie_data'] = ram_pie_data
    stats_data['cpu_ram_data'] = cpu_ram_data
    stats_data['bot_cpu_process'] = bot_cpu_process
    stats_data['bot_ram_process'] = bot_ram_process
    stats_data['bot_ram_process_percent'] = bot_ram_process_percent
    print("Dashboard data prepared:", {
        'sizes_data': sizes_data,
        'versions_data': versions_data,
        'cpu_pie_data': cpu_pie_data,
        'ram_pie_data': ram_pie_data,
        'cpu_ram_data': cpu_ram_data,
        'cpu_total_usage': cpu_percent,
        'cpu_total_free': 100 - cpu_percent,
        'ram_total_usage': ram_percent,
        'ram_total_free': 100 - ram_percent,
        'ram_total': ram_total,
        'ram_used': ram_used,
        'ram_free': ram_free,
        'cpu_process': cpu_process,
        'ram_process': ram_process,
        'bot_cpu_process': bot_cpu_process,
        'bot_ram_process': bot_ram_process,
        'bot_ram_process_percent': bot_ram_process_percent
    })
    return render_template('index.html',
                           sizes_data=sizes_data,
                           versions_data=versions_data,
                           messages_data=messages_data,
                           cpu_pie_data=cpu_pie_data,
                           ram_pie_data=ram_pie_data,
                           cpu_ram_data=cpu_ram_data,
                           cpu_total_usage=cpu_percent,
                           cpu_total_free=100 - cpu_percent,
                           ram_total_usage=ram_percent,
                           ram_total_free=100 - ram_percent,
                           ram_total=ram_total,
                           ram_used=ram_used,
                           ram_free=ram_free,
                           cpu_process=cpu_process,
                           ram_process=ram_process,
                           bot_cpu_process=bot_cpu_process,
                           bot_ram_process=bot_ram_process,
                           bot_ram_process_percent=bot_ram_process_percent)

@app.route('/stat')
def stat():
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        ram_percent = ram.percent
        ram_total = ram.total / (1024 ** 3)  
        ram_used = ram.used / (1024 ** 3)   
        ram_free = ram.available / (1024 ** 3)

        process = psutil.Process()
        cpu_process = process.cpu_percent(interval=1)
        ram_process = process.memory_info().rss / (1024 ** 2)
        ram_process_percent = (ram_process / 1024) / ram_total * 100

        # Get bot process specs
        bot_process = get_bot_process()
        if bot_process:
            try:
                bot_cpu_process = bot_process.cpu_percent(interval=1)
                bot_ram_process = bot_process.memory_info().rss / (1024 ** 2)
                bot_ram_process_percent = (bot_ram_process / 1024) / ram_total * 100
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                bot_cpu_process = 0
                bot_ram_process = 0
                bot_ram_process_percent = 0
        else:
            bot_cpu_process = 0
            bot_ram_process = 0
            bot_ram_process_percent = 0

        try:
            response = requests.get("http://localhost:8080/specs", timeout=2)
            if response.status_code == 200:
                data = response.json()
                transformed = {
                    'sizes_data': stats_data['sizes_data'],
                    'versions_data': stats_data['versions_data'],
                    'messages_data': stats_data['messages_data'],
                    'cpu_pie_data': [
                        {"label": "Process", "value": cpu_process},
                        {"label": "System", "value": data.get("cpu_percent", 0) - cpu_process},
                        {"label": "Free", "value": 100 - data.get("cpu_percent", 0)}
                    ],
                    'ram_pie_data': [
                        {"label": "Process", "value": ram_process_percent},
                        {"label": "System", "value": data.get("ram_percent", 0) - ram_process_percent},
                        {"label": "Free", "value": 100 - data.get("ram_percent", 0)}
                    ],
                    'cpu_ram_data': [],
                    'cpu_total_usage': cpu_percent,
                    'cpu_total_free': 100 - cpu_percent,
                    'ram_total_usage': ram_percent,
                    'ram_total_free': 100 - ram_percent,
                    'ram_total': ram_total,
                    'ram_used': ram_used,
                    'ram_free': ram_free,
                    'cpu_process': cpu_process,
                    'ram_process': ram_process,
                    'bot_cpu_process': bot_cpu_process,
                    'bot_ram_process': bot_ram_process,
                    'bot_ram_process_percent': bot_ram_process_percent
                }
                return jsonify(transformed)
        except requests.RequestException:
            pass

        stats_data['cpu_pie_data'] = [
            {"label": "Process", "value": cpu_process},
            {"label": "System", "value": cpu_percent - cpu_process},
            {"label": "Free", "value": 100 - cpu_percent}
        ]
        stats_data['ram_pie_data'] = [
            {"label": "Process", "value": ram_process_percent},
            {"label": "System", "value": ram_percent - ram_process_percent},
            {"label": "Free", "value": 100 - ram_percent}
        ]
        stats_data['cpu_total_usage'] = cpu_percent
        stats_data['cpu_total_free'] = 100 - cpu_percent
        stats_data['ram_total_usage'] = ram_percent
        stats_data['ram_total_free'] = 100 - ram_percent
        stats_data['ram_total'] = ram_total
        stats_data['ram_used'] = ram_used
        stats_data['ram_free'] = ram_free
        stats_data['cpu_process'] = cpu_process
        stats_data['ram_process'] = ram_process
        stats_data['bot_cpu_process'] = bot_cpu_process
        stats_data['bot_ram_process'] = bot_ram_process
        stats_data['bot_ram_process_percent'] = bot_ram_process_percent

        return jsonify(stats_data)
    except Exception as e:
        app.logger.error(f"Error in stat route: {e}")
        return jsonify({"error": "An error occurred"}), 500
    
@app.route('/top_servers')
def top_servers():
    try:
        response = requests.get("http://localhost:8080/bot_stats", timeout=2)
        if response.status_code == 200:
            data = response.json()
            result = {
                'uptime': data.get('uptime', 'N/A'),
                'servers': str(data.get('servers', 0)),
                'total_users': str(data.get('total_users', 0)),
                'total_messages': str(data.get('total_messages', 0)),
                'server_size_breakdown': [
                    {'server_name': size, 'usage': f"{count} servers"}
                    for size, count in data.get('server_size_breakdown', {}).items()
                ]
            }
            return jsonify(result)
        else:
            return jsonify({
                'uptime': 'N/A',
                'servers': '0',
                'total_users': '0',
                'total_messages': '0',
                'server_size_breakdown': []
            })
    except requests.RequestException:
        return jsonify({
            'uptime': 'N/A',
            'servers': '0',
            'total_users': '0',
            'total_messages': '0',
            'server_size_breakdown': []
        })
    except Exception as e:
        app.logger.error(f"Error in top_servers route: {e}")
        return jsonify({"error": "An error occurred"}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0",debug=False, port=5000) # WEBSERVER PORT
