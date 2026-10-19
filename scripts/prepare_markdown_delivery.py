"""Render a bounded, reviewable Cloudflare diagnostic; never changes Cloudflare."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


PLAN = Path(__file__).resolve().parents[1] / 'docs/cloudflare-markdown-fallback.json'


def prepare_diagnostic(start, duration=180, kind='diagnostic'):
    if not isinstance(start, int) or isinstance(start, bool) or start <= 0:
        raise ValueError('start must be a positive UTC Unix second')
    if not isinstance(duration, int) or isinstance(duration, bool) or not 1 <= duration <= 180:
        raise ValueError('duration must be 1–180 seconds')
    if kind not in {'diagnostic', 'root_trial'}:
        raise ValueError('only diagnostic or root_trial can be prepared')
    template = json.loads(PLAN.read_text())[kind]
    rule = json.loads(json.dumps(template['rule']).replace('START_SECOND', str(start)).replace('END_SECOND', str(start + duration)))
    return {
        'status': 'prepared_not_applied',
        'kind': kind,
        'starts_at': datetime.fromtimestamp(start, timezone.utc).isoformat(),
        'expires_at': datetime.fromtimestamp(start + duration, timezone.utc).isoformat(),
        'duration_seconds': duration,
        'phase': template['phase'],
        'rule': rule,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=int, required=True, help='UTC Unix second; allow time to review/save before this start')
    parser.add_argument('--duration', type=int, default=180)
    parser.add_argument('--kind', choices=['diagnostic', 'root-trial'], default='diagnostic')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare_diagnostic(args.start, args.duration, args.kind.replace('-', '_'))
        if args.start <= int(datetime.now(timezone.utc).timestamp()):
            raise ValueError('choose a future window; an expired window is not a new observation')
    except (ValueError, OverflowError, OSError) as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f"Prepared only: {result['starts_at']} → {result['expires_at']}; {args.out}")
