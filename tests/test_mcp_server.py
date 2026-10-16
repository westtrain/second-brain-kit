import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'scripts'))
from brain_access import BrainAccess
from mcp_config import configuration

HAS_MCP = importlib.util.find_spec('mcp') is not None
if HAS_MCP:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client


def fingerprint(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


@unittest.skipUnless(HAS_MCP, 'optional MCP SDK is not installed')
class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_official_client_handshake_read_scope_and_disabled_writes(self):
        root = (SOURCE / 'examples/search-eval/work').resolve()
        before = fingerprint(root)
        parameters = StdioServerParameters(command=sys.executable, args=[str(SOURCE / 'scripts/mcp_server.py'),
                                            '--root', str(root), '--scope', 'work'])
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                self.assertEqual(initialized.serverInfo.name, 'second-brain-work')
                tools = await session.list_tools()
                self.assertEqual({t.name for t in tools.tools},
                                 {'brain_info', 'search', 'get_document', 'project_catalog', 'project_snapshot'})
                self.assertTrue(all(t.annotations.readOnlyHint for t in tools.tools))
                result = await session.call_tool('search', {'query': '문서에 없는 가상 질문'})
                self.assertFalse(result.isError)
                self.assertEqual(result.structuredContent['results'], [])
                found = await session.call_tool('search', {'query': '검토', 'scope': 'personal'})
                if not found.isError:
                    self.assertEqual(found.structuredContent['scope'], 'work')
                found = await session.call_tool('search', {'query': '문서 검토'})
                doc = found.structuredContent['results'][0]
                reread = await session.call_tool('get_document', {'document_id': doc['document_id']})
                self.assertEqual(reread.structuredContent['content_hash'], doc['content_hash'])
                for name, args in [('record_session', {'summary': 'not authorized'}),
                                   ('get_document', {'document_id': '../system/scope.json'}),
                                   ('search', {'query': 'x', 'limit': 0})]:
                    rejected = await session.call_tool(name, args)
                    self.assertTrue(rejected.isError, name)
        self.assertEqual(fingerprint(root), before)

    async def test_write_tools_use_real_worktrees_and_stale_integrations_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve() / 'brain'
            created = subprocess.run([sys.executable, str(SOURCE / 'scripts/init_brain.py'),
                                      '--scope', 'work', '--target', str(root)], capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            parameters = StdioServerParameters(command=sys.executable, args=[str(SOURCE / 'scripts/mcp_server.py'),
                                                '--root', str(root), '--scope', 'work', '--enable-writes'])
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertEqual(len(tools.tools), 9)
                    async def call(name, args):
                        result = await session.call_tool(name, args)
                        self.assertFalse(result.isError, str(result.content))
                        return result.structuredContent
                    catalog = await call('project_catalog', {})
                    registered = await call('register_project', dict(expected_registry=catalog['expected_registry'],
                                            project_id='sample-app', title='가상 앱', purpose='MCP test only',
                                            source='synthetic test', risk='routine'))
                    self.assertEqual(registered['state'], 'merged')
                    current = lambda: subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'])
                    before = current()
                    reviewed = await call('record_session', dict(project='sample-app', session='review-test',
                                          source='synthetic test', summary='검토용 가상 기록'))
                    self.assertEqual(reviewed['state'], 'review')
                    self.assertEqual(current(), before)
                    recorded = await call('record_session', dict(project='sample-app', session='current-test',
                                          source='synthetic test', observed='2026-01-15',
                                          summary='구현 완료. 배포는 대기 중.', risk='routine'))
                    self.assertEqual(recorded['state'], 'merged')
                    self.assertNotEqual(current(), before)
                    state = await call('project_snapshot', {'project': 'sample-app'})
                    self.assertEqual(len(state['pending']), 1)
                    event_path = state['pending'][0]['path']
                    today = datetime.date.today().isoformat()
                    markdown = (f'---\nstatus: confirmed\nupdated: {today}\nas_of: 2026-01-15\n'
                                'source: synthetic test\n---\n# 가상 앱\n\n'
                                '## Current Status\n구현 완료. 배포 대기.\n'
                                '## Next Actions\n배포 검증.\n## Blockers\n없음\n'
                                f'## History\n[근거](../{event_path})\n## Decisions\n검증 후 배포.\n')
                    request = dict(project='sample-app', expected=state['expected'],
                                   events=[state['pending'][0]['id']], mode='current', markdown=markdown, risk='routine')
                    integrated = await call('integrate_project', request)
                    self.assertEqual(integrated['state'], 'merged')
                    self.assertEqual((await call('project_snapshot', {'project': 'sample-app'}))['pending'], [])
                    before = current()
                    rejected = await session.call_tool('integrate_project', request)
                    self.assertTrue(rejected.isError)
                    self.assertEqual(current(), before)
                    # Even with writes enabled, adding any remote blocks publication by MCP.
                    subprocess.run(['git', '-C', str(root), 'remote', 'add', 'upstream',
                                    'https://example.invalid/not-a-destination.git'], check=True)
                    rejected = await session.call_tool('record_session', dict(project='sample-app', session='remote',
                                      source='synthetic', summary='must not publish', risk='routine'))
                    self.assertTrue(rejected.isError)
                    self.assertEqual(current(), before)


class WritePolicyTests(unittest.TestCase):
    def test_direct_mutations_are_denied_without_opt_in(self):
        access = BrainAccess((SOURCE / 'examples/search-eval/personal').resolve(), 'personal')
        with self.assertRaisesRegex(ValueError, 'disabled'):
            access.mutate('record', 'x')

    def test_connection_config_does_not_activate_writes_or_modify_files(self):
        root = (SOURCE / 'examples/search-eval/personal').resolve()
        before = fingerprint(root)
        config = configuration(root, 'personal')
        self.assertNotIn('--enable-writes', config['args'])
        self.assertEqual(config['args'][config['args'].index('--root') + 1], str(root))
        self.assertEqual(fingerprint(root), before)
        with self.assertRaises(ValueError):
            configuration(root, 'work')


if __name__ == '__main__':
    unittest.main()
