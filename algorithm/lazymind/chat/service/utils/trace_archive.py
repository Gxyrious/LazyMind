import logging
import threading
import time

_logger = logging.getLogger(__name__)

_MAINTAIN_LOCAL_TRACES_INTERVAL = 86400  # 24 hours


def _run_once():
    try:
        from lazyllm.tracing.backends.local import maintain_local_traces
        result = maintain_local_traces()
        if result['compressed_jsonl'] or result['deleted_zip']:
            _logger.info(
                'local trace maintenance: compressed=%d, deleted=%d',
                len(result['compressed_jsonl']),
                len(result['deleted_zip']),
            )
    except Exception:
        _logger.warning('local trace maintenance failed', exc_info=True)


def start_local_trace_maintenance():
    from lazyllm.configs import config
    if config['trace_backend'] != 'local':
        return

    def _loop():
        _run_once()
        while True:
            time.sleep(_MAINTAIN_LOCAL_TRACES_INTERVAL)
            _run_once()

    t = threading.Thread(target=_loop, name='local-trace-maintenance', daemon=True)
    t.start()
