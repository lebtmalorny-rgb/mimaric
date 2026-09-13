"""Operator lifecycle; bounded JSON output and deliberately sanitized errors."""
import argparse
import json
import sys

from oslo_config import cfg

from . import config
from .etcd import GuardError, GuardDenied


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse messages may contain supplied URLs, passwords or invalid values.
        raise GuardDenied('Invalid command arguments; use --help')


def parser():
    result = Parser(prog='powerops-evacuation-guard')
    result.add_argument('--config-file', action='append', default=[])
    subs = result.add_subparsers(dest='command', required=True)
    for name in ('initialize', 'configure', 'status', 'inspect-operation', 'inspect-intent',
                 'recover-cooldown', 'resolve-operation', 'resolve-intent'):
        sub = subs.add_parser(name)
        if name == 'status':
            sub.add_argument('--limit', type=int, default=100)
            sub.add_argument('--cursor')
        if name in ('inspect-operation', 'recover-cooldown', 'resolve-operation'):
            sub.add_argument('migration_uuid')
        if name in ('inspect-intent', 'resolve-intent'):
            sub.add_argument('attempt_uuid')
        if name in ('initialize', 'configure', 'recover-cooldown', 'resolve-operation', 'resolve-intent'):
            sub.add_argument('--actor', required=True)
            sub.add_argument('--reason', required=True)
        if name in ('configure', 'recover-cooldown', 'resolve-operation', 'resolve-intent'):
            sub.add_argument('--expected-revision', required=True, type=int)
        if name == 'configure':
            sub.add_argument('--max-parallel', required=True, type=int)
            sub.add_argument('--cooldown', required=True, type=float)
        if name in ('resolve-operation', 'resolve-intent'):
            sub.add_argument('--nova-terminal', action='store_true', required=True)
            sub.add_argument('--executors-quiesced', action='store_true', required=True)
    return result


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        conf = cfg.ConfigOpts()
        config.register_opts(conf)
        conf(args=[], default_config_files=args.config_file)
        guard = config.from_conf(conf)
        common = lambda: dict(expected_revision=args.expected_revision, actor=args.actor, reason=args.reason)
        if args.command == 'initialize':
            output = guard.initialize(args.actor, args.reason)
        elif args.command == 'configure':
            output = guard.configure(max_parallel=args.max_parallel, cooldown=args.cooldown, **common())
        elif args.command == 'status':
            output = guard.status(args.limit, args.cursor)
        elif args.command == 'inspect-operation':
            output = guard.get_operation(args.migration_uuid)
        elif args.command == 'inspect-intent':
            output = guard.get_intent(args.attempt_uuid)
        elif args.command == 'recover-cooldown':
            output = guard.recover_cooldown(args.migration_uuid, **common())
        elif args.command == 'resolve-operation':
            output = guard.resolve(args.migration_uuid, nova_terminal=args.nova_terminal,
                                   executors_quiesced=args.executors_quiesced, **common())
        else:
            output = guard.resolve_intent(args.attempt_uuid, nova_terminal=args.nova_terminal,
                                          executors_quiesced=args.executors_quiesced, **common())
        print(json.dumps(output, sort_keys=True, allow_nan=False))
        return 0
    except (GuardError, cfg.Error, ValueError, TypeError, OSError):
        # Never interpolate exceptions (URLs, remote bodies, config values or paths).
        print('Evacuation guard command denied or unavailable; inspect configuration and durable state.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
