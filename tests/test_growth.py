import copy
from pathlib import Path
import tempfile
import unittest
from test_profile import app, event, FakeAPI, ROOT


class GrowthTests(unittest.TestCase):
    def setUp(self):
        self.cfg = app.read_json(ROOT/'tests/fixture.json')
        self.cfg['growth'] = {'automatic': True, 'recent_prs': 20}
        self.cfg['github']['sources'][0]['mode'] = 'prs'
        self.cfg['github']['auto_classify'] = True

    def test_split_preserves_total_and_rounding(self):
        result = app.allocate(10, {'code':1, 'test':1, 'share':1}, self.cfg['stats'])
        self.assertEqual(result, {'code':4, 'test':3, 'share':3})
        state = app.score(self.cfg, [event(weights={'code':1, 'test':2})])
        self.assertEqual(state['stats']['code'], 10)
        self.assertEqual(state['stats']['test'], 20)
        self.assertEqual(state['total_xp'], 30)

    def test_invalid_weights_fail(self):
        for weights in [{}, {'code':0}, {'code':-1}, {'unknown':1}, {'code':True}]:
            with self.assertRaises(ValueError):
                app.score(self.cfg, [event(weights=weights)])

    def test_no_pr_is_normal_and_manual_does_not_change_types(self):
        state = app.score(self.cfg, [event()])
        self.assertEqual(state['types'], ['NORMAL'])
        self.assertEqual(state['recent_pr_count'], 0)

    def test_recent_window_changes_type_but_keeps_lifetime_xp(self):
        self.cfg['growth']['recent_prs'] = 2
        events = [event('manual:one',kind='feat',source='github-pr',stat='code'),
                  event('manual:two',kind='test',source='github-pr',stat='test'),
                  event('manual:three',kind='test',source='github-pr',stat='test')]
        # Use explicit ordered timestamps rather than relying on ID lexicography.
        for i,e in enumerate(events):e['date']=f'2026-11-23T1{i}:00:00Z'
        state = app.score(self.cfg, events)
        self.assertEqual(state['types'], ['TEST'])
        self.assertEqual(state['total_xp'], 60)
        self.assertIn('たしかめじょうず',state['trait'])

    def test_equal_type_xp_uses_most_recent_contribution(self):
        events=[event('gh:o/r:pr:1','docs',date='2026-11-23T10:00:00Z'),
                event('gh:o/r:pr:2','test',date='2026-11-23T11:00:00Z')]
        state=app.score(self.cfg,events)
        self.assertEqual(state['types'],['TEST','SHARE'])

    def test_paths_and_labels(self):
        pr={'title':'保存フォームの改善','labels':[]}
        kind, stat, weights=app.classify_pr(pr,['src/form.ts','tests/test_form.py','README.md'],self.cfg,{})
        self.assertEqual(kind,'feat')
        self.assertEqual(weights,{'code':1,'test':1,'share':1})
        self.assertEqual(app.classify_pr(pr,['docs/linear_algebra.tex'],self.cfg,{})[0],'study')
        pr['labels']=[{'name':'xp:fix'},{'name':'stat:electric'}]
        self.assertEqual(app.classify_pr(pr,['src/form.ts'],self.cfg,{}),('fix','electric',{'electric':1}))
        pr['labels']=[{'name':'xp:skip'}]
        self.assertIsNone(app.classify_pr(pr,['src/form.ts'],self.cfg,{}))

    def test_maintenance_is_not_guessed_as_feature(self):
        for title in ['chore: housekeeping','ci: automated profile','qualification: license']:
            self.assertIsNone(app.classify_pr({'title':title,'labels':[]},['src/app.py'],self.cfg,{}))

    def test_manual_scope_overrides_paths(self):
        self.assertEqual(app.classify_pr({'title':'docs(math): 証明','labels':[]},['README.md'],self.cfg,{}),
                         ('docs','math',{'math':1}))

    def test_pr_sync_fetches_files_and_is_idempotent(self):
        pr={'number':1,'updated_at':'2026-11-23T12:00:00Z','merged_at':'2026-11-23T11:00:00Z',
            'user':{'login':'mitsuki-nyann','type':'User'},'title':'保存フォームの改善',
            'labels':[],'html_url':'https://github.com/example/pull/1'}
        class API(FakeAPI):
            file_calls=0
            def pages(self,path,**query):
                if path.endswith('/files'):
                    self.file_calls+=1
                    yield from [{'filename':'src/app.py'},{'filename':'tests/test_app.py'}]
                else:yield pr
        api=API([])
        first=app.collect(self.cfg,api,[])
        self.assertEqual(first[0]['weights'],{'code':1,'test':1})
        self.assertEqual(app.collect(self.cfg,api,first),first)
        self.assertEqual(api.file_calls,1)
        state=app.score(self.cfg,first)
        self.assertEqual(state['total_xp'],30)
        self.assertEqual(state['recent_pr_count'],1)

    def test_avatar_embedded_not_external_and_root_guard(self):
        cfg=copy.deepcopy(self.cfg)
        cfg['avatar']='assets/maid.png'
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'assets').mkdir()
            (root/'assets/maid.png').write_bytes((ROOT/'assets/maid.png').read_bytes())
            app.build(root,cfg,[])
            svg=(root/'generated/profile.svg').read_text()
            self.assertIn('data:image/png;base64,',svg)
            self.assertNotIn('<script',svg)
            cfg['avatar']='../outside.png'
            with self.assertRaises(ValueError):app.build(root,cfg,[])

    def test_private_source_only_saves_sanitized_events(self):
        self.cfg['github']['sources'][0]['private_summary']=True
        pr={'number':123,'updated_at':'2026-11-23T12:00:00Z','merged_at':'2026-11-23T11:00:00Z',
            'user':{'login':'mitsuki-nyann','type':'User'},'title':'feat: SECRET-PROJECT-NAME',
            'labels':[],'html_url':'https://github.com/private/pull/123'}
        class API(FakeAPI):
            def pages(self,path,**query):
                if path.endswith('/files'):yield {'filename':'src/SECRET-FILE.py'}
                else:yield pr
        api=API([],private=True)
        items=app.collect(self.cfg,api,[])
        output=app.json_text(items)
        for secret in ['SECRET','https://github.com/private','example-project']:
            self.assertNotIn(secret,output)
        self.assertTrue(items[0]['id'].startswith('private:'))
        self.assertEqual(app.collect(self.cfg,api,items),items)
        self.assertEqual(app.score(self.cfg,items)['types'],['CODE'])

    def test_private_token_pending_is_explicit_and_does_not_mutate_config(self):
        self.cfg['github']['sources'][0]['private_summary']=True
        effective,status=app.sync_config(self.cfg,None)
        self.assertEqual(effective['github']['sources'],[])
        self.assertEqual(status['private_sources_pending'],1)
        self.assertEqual(len(self.cfg['github']['sources']),1)
        effective,status=app.sync_config(self.cfg,'test-token')
        self.assertEqual(len(effective['github']['sources']),1)
        self.assertEqual(status['private_sources_pending'],0)

    def test_private_sources_from_secret_never_modify_public_config(self):
        self.cfg['github']['sources']=[]
        effective,status=app.sync_config(self.cfg,'test-token','sample-owner/sample-private')
        self.assertEqual(effective['github']['sources'][0]['repo'],'sample-owner/sample-private')
        self.assertEqual(self.cfg['github']['sources'],[])
        self.assertNotIn('sample-private',app.json_text(status))
        self.assertEqual(status['private_sync'],'configured')
        _,status=app.sync_config(self.cfg,None,'')
        self.assertEqual(status['private_sync'],'awaiting_configuration')


if __name__=='__main__':unittest.main()
