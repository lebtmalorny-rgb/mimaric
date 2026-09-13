"""Explicit operator initialization and recovery acknowledgement."""
import argparse
import json
import sys

from oslo_config import cfg

from powerops_watcher_guard import config
from powerops_watcher_guard.gate import GuardDenied


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # Argument/config errors may contain credentials or other supplied text.
        raise ValueError('Invalid command arguments')


def _parser():
    parser = _Parser(description=__doc__)
    parser.add_argument('--config-file', required=True)
    commands = parser.add_subparsers(dest='command', required=True, parser_class=_Parser)
    commands.add_parser('status', help='Read current state and its revision')
    for command in ('initialize', 'resume'):
        operation = commands.add_parser(command)
        operation.add_argument('--actor', required=True)
        operation.add_argument('--reason', required=True)
        if command == 'resume':
            operation.add_argument('--expected-revision', type=int, required=True)
            operation.add_argument('--acknowledge-recovery', action='store_true', required=True)
    return parser


def main(argv=None):
    try:
        args = _parser().parse_args(argv)
        conf = cfg.ConfigOpts()
        config.register_opts(conf)
        conf(args=[], default_config_files=[args.config_file])
        gate = config.from_conf(conf)
        if args.command == 'status':
            state = gate.status()
        elif args.command == 'initialize':
            state = gate.initialize(args.actor, args.reason)
        else:
            state = gate.resume(args.expected_revision, args.actor, args.reason)
        print(json.dumps(state, sort_keys=True))
        return 0
    except GuardDenied as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}), file=sys.stderr)
        return 1
    except (cfg.Error, ValueError, OSError):
        print(json.dumps({'error': 'Invalid arguments or guard configuration'}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
