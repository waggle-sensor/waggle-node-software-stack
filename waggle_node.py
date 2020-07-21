import argparse
import os
import os.path
import subprocess
import secrets
from hashlib import sha256
from base64 import b64encode
import sys
from pathlib import Path
import json
import re
from shutil import copytree
import unittest

TEMPLATE_DIR = Path(sys.argv[0]).parent / 'templates'
TEMPLATE_NAMES = [p.name for p in TEMPLATE_DIR.glob('*/')]


def fatal(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)
    sys.exit(1)


def run_quiet(*args, **kwargs):
    return subprocess.run(*args, **kwargs, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def command_up(args):
    r = subprocess.run(['docker-compose', '-p', args.project_name, 'up', '-d'])
    sys.exit(r.returncode)


def remove_file_if_exists(path):
    try:
        path.unlink()
        print(f'Cleaned up {path}')
    except FileNotFoundError:
        pass


def command_down(args):
    r = subprocess.run(
        ['docker-compose', '-p', args.project_name, 'down', '--remove-orphans'])
    remove_file_if_exists(Path('private/key.pem'))
    remove_file_if_exists(Path('private/cert.pem'))
    remove_file_if_exists(Path('private/cacert.pem'))
    remove_file_if_exists(Path('private/reverse_ssh_port'))
    sys.exit(r.returncode)


def command_logs(args):
    r = subprocess.run(
        ['docker-compose', '-p', args.project_name, 'logs', '-f'])
    sys.exit(r.returncode)


def generate_random_password():
    return secrets.token_hex(20)


# TODO Save in case we move back to API instead of rabbitmqctl
# def rabbitmq_password_hash(password):
#     salt = bytes([0x90, 0x8d, 0xc6, 0x0a])
#     data = password.encode()
#     return b64encode(salt + sha256(salt + data).digest()).decode()


def get_docker_image_labels(image):
    results = json.loads(subprocess.check_output(['docker', 'inspect', image]))
    return {k: v for r in results for k, v in r['ContainerConfig']['Labels'].items()}


def setup_rabbitmq_user(args, username, password):
    run_quiet([
        'docker-compose', 'exec', 'rabbitmq',
        'rabbitmqctl',
        'add_user',
        username,
        password,
    ])

    run_quiet([
        'docker-compose', 'exec', 'rabbitmq',
        'rabbitmqctl',
        'change_password',
        username,
        password,
    ])

    run_quiet([
        'docker-compose', 'exec', 'rabbitmq',
        'rabbitmqctl',
        'set_permissions',
        username,
        '.*',
        '.*',
        '.*',
    ])


def has_plugin(plugin):
    try:
        run_quiet(['docker', 'inspect', plugin], check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def command_run(args):
    if not has_plugin(args.plugin):
        print(
            f'Did not find plugin {args.plugin} locally. Pulling from remote...')
        try:
            subprocess.check_call(['docker', 'pull', args.plugin])
        except subprocess.CalledProcessError:
            fatal(f'Failed to pull plugin {args.plugin}')

    labels = get_docker_image_labels(args.plugin)

    plugin_id = int(labels['waggle.plugin.id'])
    plugin_version = labels['waggle.plugin.version']
    plugin_name = labels['waggle.plugin.name']
    plugin_instance = 0
    plugin_username = f'plugin-{plugin_id}-{plugin_version}-{plugin_instance}'
    plugin_password = generate_random_password()
    # TODO add back in support for devices / volumes

    print(f'Setting up {args.plugin}')
    setup_rabbitmq_user(args, plugin_username, plugin_password)

    network = f'{args.project_name}_waggle'
    name = f'{args.project_name}_plugin-{plugin_name}-{plugin_version}-{plugin_instance}'

    run_quiet(['docker', 'rm', '-f', name])

    try:
        print(f'Running {args.plugin}\n')

        subprocess.run([
            'docker', 'run', '-it',
            '--name', name,
            '--network', network,
            '--env-file', 'waggle-node.env',
            '--restart', 'on-failure',
            '-e', f'WAGGLE_PLUGIN_ID={plugin_id}',
            '-e', f'WAGGLE_PLUGIN_VERSION={plugin_version}',
            '-e', f'WAGGLE_PLUGIN_INSTANCE={plugin_instance}',
            '-e', f'WAGGLE_PLUGIN_USERNAME={plugin_username}',
            '-e', f'WAGGLE_PLUGIN_PASSWORD={plugin_password}',
            args.plugin,
        ])
    finally:
        print(f'Cleaning up {args.plugin}')
        run_quiet(['docker', 'rm', '-f', name])


def get_build_args_from_list(ls):
    results = []
    for a in ls:
        results += ['--build-arg', a]
    return results


def get_build_args_from_dict(d):
    return get_build_args_from_list(f'{k}={v}' for k, v in d.items())


def command_build(args):
    if not args.plugin_dir.is_dir():
        fatal('error: argument must point to base directory of a plugin')

    try:
        config = json.loads((args.plugin_dir / 'sage.json').read_text())
    except FileNotFoundError:
        fatal('error: plugin is missing sage.json metadata file')

    image_name = 'plugin-{name}:{version}'.format(**config)

    # check for expected fields
    missing_keys = {'id', 'version', 'name'} - set(config.keys())

    if missing_keys:
        fatal('error: sage.json is missing fields', missing_keys)

    user_args = (get_build_args_from_list(args.build_args) +
                 get_build_args_from_dict(config.get('build_args', {})))

    r = subprocess.run([
        'docker',
        'build',
        *user_args,
        '--label', 'waggle.plugin.id={id}'.format(**config),
        '--label', 'waggle.plugin.version={version}'.format(**config),
        '--label', 'waggle.plugin.name={name}'.format(**config),
        '-t', image_name,
        str(args.plugin_dir),
    ], stdout=sys.stderr, stderr=sys.stderr)
    print(image_name)
    sys.exit(r.returncode)


sage_json_template = '''{{
    "architecture": [
        "linux/amd64",
        "linux/arm/v7",
        "linux/arm64"
    ],
    "arguments": [],
    "description": "My cool new plugin called {name}",
    "inputs": [],
    "metadata": {{}},
    "id": 1000,
    "name": "{name}",
    "namespace": "waggle",
    "source": "URL for repo",
    "version": "0.0.1"
}}
'''


def plugin_name_valid(s):
    return re.match('[a-z0-9_-]+$', s) is not None


def command_new_plugin(args):
    if not plugin_name_valid(args.name):
        fatal(f'plugin names can only contain lowercase letters, numbers, _ and -.')

    plugin_dir = Path(f'plugin-{args.name}')

    try:
        copytree(TEMPLATE_DIR / args.template, plugin_dir)
    except FileExistsError:
        fatal(f'warning: plugin directory {plugin_dir} already exists')

    (plugin_dir / 'sage.json').write_text(sage_json_template.format(name=args.name))


def command_report(args):
    print('=== RabbitMQ Queue Status ===')
    subprocess.run(['docker-compose', 'exec', 'rabbitmq',
                    'rabbitmqctl', 'list_queues'])
    print()
    print('=== RabbitMQ Shovel Status ===')
    subprocess.run(['docker-compose', 'exec', 'rabbitmq',
                    'rabbitmqctl', 'eval', 'rabbit_shovel_status:status().'])


def main():
    parser = argparse.ArgumentParser()
    parser.set_defaults(func=lambda args: parser.print_help())
    parser.add_argument('-p', '--project-name',
                        default=os.path.basename(os.getcwd()), help='specify project name (default: directory name)')

    subparsers = parser.add_subparsers()

    parser_up = subparsers.add_parser(
        'up', help='start virtual waggle environment')
    parser_up.set_defaults(func=command_up)

    parser_down = subparsers.add_parser(
        'down', help='stop virtual waggle environment')
    parser_down.set_defaults(func=command_down)

    parser_logs = subparsers.add_parser(
        'logs', help='show virtual waggle system logs')
    parser_logs.add_argument('-f', action='store_true', help='follow logs')
    parser_logs.set_defaults(func=command_logs)

    parser_report = subparsers.add_parser(
        'report', help='show virtual waggle system report for debugging')
    parser_report.set_defaults(func=command_report)

    parser_build = subparsers.add_parser(
        'build', help='build plugin for virtual waggle from a directory')
    parser_build.add_argument('--build-arg', action='append', default=[])
    parser_build.add_argument(
        'plugin_dir', type=Path, help='base directory of plugin to build')
    parser_build.set_defaults(func=command_build)

    parser_run = subparsers.add_parser(
        'run', help='runs a plugin inside virtual waggle environment')
    parser_run.add_argument('plugin', help='plugin to run')
    parser_run.set_defaults(func=command_run)

    parser_new_plugin = subparsers.add_parser(
        'newplugin', help='generates a new plugin')
    parser_new_plugin.add_argument(
        '-t', '--template', default='simple', choices=TEMPLATE_NAMES, help='plugin template to use')
    parser_new_plugin.add_argument('name', help='name of plugin')
    parser_new_plugin.set_defaults(func=command_new_plugin)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()