web: gunicorn --bind 0.0.0.0:$PORT --worker-class gevent --workers 1 --threads 4 --timeout 120 bot.server:app
worker: python -m bot.main