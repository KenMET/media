import json,time,unittest
from media_mcp.adapters.codex import CodexClient,CodexError,_Session
from media_mcp.ingest.clients.library_analysis import LibraryAnalysisClient

class Socket:
    def __init__(self,events):self.events=iter(events)
    def settimeout(self,value):pass
    def recv(self):return json.dumps(next(self.events))

def item(kind,ident='one',**extra):
    return {'method':'item/completed','params':{'threadId':'thread','turnId':'turn','item':{'type':kind,'id':ident,**extra}}}

class ResearchTransportTests(unittest.TestCase):
    def session(self,events,observe=True):
        session=_Session(Socket(events),time.monotonic()+10)
        if observe:session.observe_web=lambda item:None
        return session
    def test_only_library_profile_enables_web_search(self):
        ordinary=CodexClient(bearer_token='fixture')
        research=LibraryAnalysisClient(bearer_token='fixture')
        self.assertEqual(ordinary._thread_params()['config']['web_search'],'disabled')
        params=research._thread_params()
        self.assertEqual(params['config']['web_search'],'live')
        self.assertEqual(params['sandbox'],'read-only')
        self.assertEqual(params['approvalPolicy'],'never')
        self.assertEqual(params['config']['mcp_servers'],{})
        self.assertFalse(params['config']['features']['shell_tool'])
    def test_web_calls_allowed_but_file_shell_and_mcp_calls_rejected(self):
        for kind in ('fileChange','commandExecution','mcpToolCall','dynamicToolCall','collabToolCall'):
            with self.subTest(kind=kind),self.assertRaisesRegex(CodexError,'unexpected_tool_call'):
                self.session([item(kind)]).wait_turn('thread','turn')
    def test_web_search_is_still_rejected_by_ordinary_clients(self):
        session=self.session([item('webSearch')],observe=False);session.reject_tool_calls=True
        with self.assertRaisesRegex(CodexError,'unexpected_tool_call'):session.wait_turn('thread','turn')
    def test_research_transport_bounds_searches_and_tracks_opened_pages(self):
        session=self.session([item('webSearch',str(n)) for n in range(25)])
        with self.assertRaisesRegex(CodexError,'search_budget_exceeded'):session.wait_turn('thread','turn')
        observed=[]
        end={'method':'turn/completed','params':{'threadId':'thread','turn':{'id':'turn','status':'completed'}}}
        session=self.session([item('webSearch',action={'type':'openPage','url':'https://www.themoviedb.org/movie/42'}),item('agentMessage',text='{}'),end])
        session.observe_web=lambda record:observed.append(record['action']['url'])
        self.assertEqual(session.wait_turn('thread','turn'),'{}')
        self.assertEqual(observed,['https://www.themoviedb.org/movie/42'])

if __name__=='__main__':unittest.main()
