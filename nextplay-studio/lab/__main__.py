import argparse
import json
from pathlib import Path
from .engine import Journal


def main():
    parser = argparse.ArgumentParser(description='NextPlay offline replay lab; no phone control')
    parser.add_argument('--db', default='studio-data/replay-lab.sqlite3')
    sub = parser.add_subparsers(dest='command', required=True)
    ingest = sub.add_parser('import')
    ingest.add_argument('session')
    ingest.add_argument('file', type=Path)
    label = sub.add_parser('label')
    label.add_argument('session')
    label.add_argument('sequence', type=int)
    label.add_argument('card', help='deck card identifier or none to withhold')
    label.add_argument('--reviewer', required=True)
    report = sub.add_parser('report')
    report.add_argument('session')
    args = parser.parse_args()
    try:
        journal = Journal(args.db)
        if args.command == 'import':
            states = json.loads(args.file.read_text())
            print(json.dumps(journal.import_session(args.session, states), indent=2))
        elif args.command == 'label':
            journal.label(args.session, args.sequence, None if args.card == 'none' else args.card, args.reviewer)
            print('Replay label saved')
        else:
            print(json.dumps(journal.report(args.session), indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f'{exc}\n')


if __name__ == '__main__':
    main()
