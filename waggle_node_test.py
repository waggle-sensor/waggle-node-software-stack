import argparse
import unittest
import waggle_node


class TestUtils(unittest.TestCase):

    def test_build_config(self):
        args = argparse.Namespace(plugin_dir='/path/to/plugin', build_arg=[])

        cmd = waggle_node.get_build_command_for_config(args, {
            'id': 123,
            'name': 'test',
            'version': '1.2.3',
            'build_args': {
                'K1': 'V1',
                'K2': 'V2',
                'K3': 'V3',
            }
        })

        self.assertEqual(cmd, [
            'docker', 'build',
            '--build-arg', 'K1=V1',
            '--build-arg', 'K2=V2',
            '--build-arg', 'K3=V3',
            '--label', 'waggle.plugin.id=123',
            '--label', 'waggle.plugin.version=1.2.3',
            '--label', 'waggle.plugin.name=test',
            '-t', 'plugin-test:1.2.3',
            '/path/to/plugin'])

    def test_image_name_for_config(self):
        name = waggle_node.get_image_name_for_config({
            'id': 123,
            'name': 'test',
            'version': '1.2.3',
            'build_args': {
                'K1': 'V1',
                'K2': 'V2',
                'K3': 'V3',
            }
        })

        self.assertEqual(name, 'plugin-test:1.2.3')

    def test_build_args_from_list(self):
        r = waggle_node.get_build_args_from_list([
            'ARG1=the',
            'ARG2=colors',
            'ARG3=duke',
        ])

        self.assertEqual(r, [
            '--build-arg', 'ARG1=the',
            '--build-arg', 'ARG2=colors',
            '--build-arg', 'ARG3=duke',
        ])

    def test_build_args_from_config(self):
        r = waggle_node.get_build_args_from_dict({
            'ARG1': 'the',
            'ARG2': 'colors',
            'ARG3': 'duke',
        })

        self.assertEqual(r, [
            '--build-arg', 'ARG1=the',
            '--build-arg', 'ARG2=colors',
            '--build-arg', 'ARG3=duke',
        ])


if __name__ == '__main__':
    unittest.main()
