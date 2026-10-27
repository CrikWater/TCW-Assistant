"""TRANSPORT/CONTROL TESTS ONLY. Fixtures are not GIS or LLM acceptance results."""
import asyncio
import json
import time
import uuid
from contextlib import contextmanager
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.config import AppError
from backend.gis_bridge import GisBridge, PROTOCOL
from backend.gis_service import GisService
from backend.owner_credentials import owner_token_path

class ControlFixtureService:
    def __init__(self, root):
        self.root, self.c, self.operation = root, {}, None
        (root / 'logs').mkdir(exist_ok=True)
    def log(self, *args, **kwargs):
        pass
    @contextmanager
    def busy(self, name):
        if self.operation:
            raise AppError('busy', 409, 'busy')
        self.operation = name
        try:
            yield
        finally:
            self.operation = None

def heartbeat(directory, **overrides):
    d = {'protocol': PROTOCOL, 'read_only': True, 'heartbeat_ms': int(time.time()*1000),
         'session_id': 'a'*32, 'busy': False, 'job_id': None}
    d.update(overrides)
    (directory/'provider.json').write_text(json.dumps(d))

async def responder(directory, mutate=None, restart=False):
    for _ in range(200):
        paths = list(directory.glob('*.request.json'))
        if paths:
            q = json.loads(paths[0].read_text())
            r = {k:q[k] for k in ('protocol','id','job_id','session_id')}
            r.update(completed_ms=int(time.time()*1000), read_only=True,
                     reply={'status':'ok','data':{'fixture':'TRANSPORT ONLY'},'map_uri':'fixture-map'})
            if mutate: mutate(r)
            if restart: heartbeat(directory, session_id='b'*32)
            else: (directory/(q['id']+'.response.json')).write_text(json.dumps(r))
            return
        await asyncio.sleep(.005)
    raise AssertionError('No transport fixture request received.')

def test_transport_and_cleanup(tmp_path):
    heartbeat(tmp_path)
    async def scenario():
        worker = asyncio.create_task(responder(tmp_path))
        r = await GisBridge(tmp_path,1,.005).call('catalog',{},uuid.uuid4().hex,'a'*32)
        await worker
        assert r['data']['fixture']=='TRANSPORT ONLY'
    asyncio.run(scenario())
    assert not list(tmp_path.glob('*.request*')) and not list(tmp_path.glob('*.response*'))

@pytest.mark.parametrize('field,value',[('id','b'*32),('job_id','c'*32),('session_id','d'*32),
    ('read_only',False),('completed_ms',0),('protocol','wrong')])
def test_uncorrelated_response_rejected(tmp_path,field,value):
    heartbeat(tmp_path)
    async def scenario():
        worker=asyncio.create_task(responder(tmp_path,lambda r:r.update({field:value})))
        with pytest.raises(AppError) as error:
            await GisBridge(tmp_path,1,.005).call('catalog',{},uuid.uuid4().hex,'a'*32)
        assert error.value.code=='gis_invalid_response'
        await worker
    asyncio.run(scenario())

def test_stale_heartbeat_and_restart(tmp_path):
    heartbeat(tmp_path,heartbeat_ms=1)
    bridge=GisBridge(tmp_path,1,.005)
    assert not bridge.status()['available']
    heartbeat(tmp_path)
    async def scenario():
        worker=asyncio.create_task(responder(tmp_path,restart=True))
        with pytest.raises(AppError) as error:
            await bridge.call('catalog',{},uuid.uuid4().hex,'a'*32)
        assert error.value.code=='gis_disconnected'
        await worker
    asyncio.run(scenario())

def test_timeout_cancels_and_cleans(tmp_path):
    heartbeat(tmp_path)
    job=uuid.uuid4().hex
    async def scenario():
        with pytest.raises(AppError) as error:
            await GisBridge(tmp_path,.06,.005).call('catalog',{},job,'a'*32)
        assert error.value.code=='gis_timeout'
    asyncio.run(scenario())
    assert (tmp_path/(job+'.cancel')).exists()
    assert not list(tmp_path.glob('*.request.json'))

def test_task_cancel_writes_marker(tmp_path):
    heartbeat(tmp_path)
    job=uuid.uuid4().hex
    async def scenario():
        task=asyncio.create_task(GisBridge(tmp_path,1,.005).call('catalog',{},job,'a'*32))
        await asyncio.sleep(.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(scenario())
    assert (tmp_path/(job+'.cancel')).exists()
    assert not list(tmp_path.glob('*.request.json'))

def test_owner_token_boundary_and_api_shape(tmp_path):
    service=ControlFixtureService(tmp_path)
    with TestClient(create_app(service,GisBridge(tmp_path))) as client:
        token=client.get('/api/session').json()['token']
        headers={'X-TCW-Token':token}
        assert client.get('/api/gis/admin/status').status_code==403
        assert client.post('/api/gis/admin/control',headers=headers,json={'action':'pause'}).status_code==403
        owner=owner_token_path(tmp_path).read_text()
        assert owner!=token and owner not in client.get('/api/session').text
        owner_headers={**headers,'X-TCW-Owner':owner}
        assert client.post('/api/gis/admin/control',headers=owner_headers,json={'action':'pause'}).json()['paused']
        assert client.post('/api/gis/ask',headers=headers,json={'question':'Any question is allowed'}).status_code==423
        assert not client.post('/api/gis/admin/control',headers=owner_headers,json={'action':'resume'}).json()['paused']
        for extra in ['tool','arguments','sql','command','action']:
            assert client.post('/api/gis/ask',headers=headers,json={'question':'A GIS question',extra:'untrusted'}).status_code==422
        assert client.get('/api/gis/status').status_code==200
    assert not owner_token_path(tmp_path).exists()

def test_host_veto_stops_pipeline_and_blocks_new_requests(tmp_path):
    heartbeat(tmp_path)
    bridge=GisBridge(tmp_path,1,.005)
    service=ControlFixtureService(tmp_path)
    controller=GisService(bridge)
    async def scenario():
        task=asyncio.create_task(controller.ask('Any open-ended GIS question',service))
        await asyncio.sleep(.02)
        job=controller.active['id']
        assert controller.control('cancel',job)['paused']
        with pytest.raises(AppError) as error: await task
        assert error.value.code=='gis_cancelled'
        assert controller.active is None and service.operation is None
        assert (tmp_path/(job+'.cancel')).exists()
        with pytest.raises(AppError) as error: await controller.ask('Different question',service)
        assert error.value.code=='gis_paused'
        controller.control('resume')
        assert not controller.paused
    asyncio.run(scenario())

def test_stale_owner_target_does_not_cancel_new_request(tmp_path):
    controller=GisService(GisBridge(tmp_path))
    controller.active={'id':'a'*32,'stage':'fixture'}
    with pytest.raises(AppError) as error: controller.control('cancel','b'*32)
    assert error.value.code=='gis_request_changed' and not controller.paused
    assert not list(tmp_path.glob('*.cancel'))

def test_unknown_arguments_rejected_before_sdk():
    spec={'parameters':{'layer_name':'string!'}}
    for args in [{'layer_name':'valves','where_clause':'DELETE FROM valves'},
                 {'layer_name':'valves','command':'anything'}, {}, 'not-an-object']:
        with pytest.raises(AppError): GisService._validate_arguments(spec,args)

@pytest.mark.parametrize('tool',['delete_feature','validate_topology','remember_operator_fact','export_csv','run_python','hydraulics'])
def test_model_cannot_escalate_tools(tmp_path,monkeypatch,tool):
    class CatalogFixture:
        calls=[]
        def status(self): return {'available':True,'session_id':'a'*32,'busy':False}
        def cancel(self,job): pass
        async def call(self,operation,payload,*args):
            self.calls.append(operation)
            assert operation=='catalog'  # No model-requested operation should reach the SDK.
            return {'data':{'tools':[{'name':'get_active_map','parameters':{}}],
                            'map':{'fixture':'TRANSPORT ONLY'}},'completed_ms':1,'map_uri':'fixture'}
    service=ControlFixtureService(tmp_path)
    service.c={'ollama_url':'http://127.0.0.1:11434','generation_model':'fixture'}
    bridge=CatalogFixture()
    controller=GisService(bridge)
    async def model(*args): return ({'name':'FIXTURE','digest':'TEST'},False)
    async def generate(*args): return {'action':'tool','tool':tool,'arguments_json':'{}','reason':'ADVERSARIAL TEST FIXTURE'}
    monkeypatch.setattr(controller,'_model',model)
    monkeypatch.setattr(controller,'_generate',generate)
    async def scenario():
        with pytest.raises(AppError) as error: await controller.ask('An unrestricted question',service)
        assert error.value.code=='gis_tool_rejected'
        assert bridge.calls==['catalog']
    asyncio.run(scenario())

def test_owner_pause_survives_controller_restart(tmp_path):
    token_path=tmp_path/'owner.token'
    first=GisService(GisBridge(tmp_path))
    first.attach_owner_path(token_path)
    first.control('pause')
    second=GisService(GisBridge(tmp_path))
    second.attach_owner_path(token_path)
    assert second.paused
    second.control('resume')
    assert not token_path.with_suffix('.paused').exists()
