import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('profile_app',ROOT/'scripts/profile.py')
app=importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def event(identity='manual:one',kind='feat',**extra):
    return {'id':identity,'kind':kind,'title':'追加した','date':'2026-11-23T12:00:00+09:00',**extra}


class FakeAPI:
    def __init__(self,items,private=False):
        self.items=items
        self.private=private
    def get(self,path,**query):
        return {'private':self.private,'default_branch':'main'}
    def pages(self,path,**query):
        yield from self.items


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.cfg=app.read_json(ROOT/'tests/fixture.json')

    def test_level_boundaries_and_stat_total(self):
        for xp,level,progress in [(0,1,0),(99,1,99),(100,2,0),(101,2,1)]:
            self.cfg['rules']['feat']['xp']=xp
            state=app.score(self.cfg,[event()])
            self.assertEqual((state['level'],state['level_xp']),(level,progress))
            self.assertEqual(state['total_xp'],sum(state['stats'].values()))

    def test_duplicate_does_not_inflate(self):
        self.assertEqual(app.score(self.cfg,[event(),event()])['total_xp'],30)
        with self.assertRaises(ValueError):
            app.score(self.cfg,[event(),event(kind='fix')])

    def test_invalid_inputs(self):
        for e in [event(id=''),event(stat='unknown'),event(date='2026-11-23')]:
            with self.assertRaises(ValueError):app.score(self.cfg,[e])
        self.cfg['rules']['feat']['xp']=-1
        with self.assertRaises(ValueError):app.score(self.cfg,[])

    def test_classification(self):
        self.assertEqual(app.classify('feat: 保存',self.cfg),('feat','code'))
        self.assertEqual(app.classify('study(electric): 複線図',self.cfg),('study','electric'))
        self.assertEqual(app.classify('refactor!: 整理',self.cfg),('refactor','design'))
        self.assertEqual(app.classify('任意のPR名',self.cfg,['xp:docs']),('docs','share'))
        for title in ['chore: 自動更新','qualification: 合格','feat: ','Update README']:
            self.assertIsNone(app.classify(title,self.cfg))
        self.assertIsNone(app.classify('feat: x',self.cfg,['xp:skip']))
        with self.assertRaises(ValueError):app.classify('feat: x',self.cfg,['xp:feat','xp:fix'])

    def commit(self,sha='abc',**extra):
        return {'sha':sha,'author':{'login':'mitsuki-nyann','type':'User'},
                'parents':[{'sha':'parent'}], 'html_url':'https://github.com/example/commit/'+sha,
                'commit':{'message':'feat: 新機能','committer':{'date':'2026-11-23T12:00:00Z'}},**extra}

    def test_commit_collection_filters_and_repeat(self):
        bot=self.commit('bot',author={'login':'mitsuki-nyann','type':'Bot'})
        other=self.commit('other',author={'login':'someone','type':'User'})
        merge=self.commit('merge',parents=[{},{}])
        old=self.commit('old',commit={'message':'feat: old','committer':{'date':'2026-11-01T00:00:00Z'}})
        unknown=self.commit('unknown',commit={'message':'chore: update','committer':{'date':'2026-11-23T12:00:00Z'}})
        api=FakeAPI([self.commit(),bot,other,merge,old,unknown])
        first=app.collect(self.cfg,api,[])
        self.assertEqual(len(first),1)
        self.assertEqual(app.collect(self.cfg,api,first),first)

    def test_private_repo_refused(self):
        with self.assertRaises(ValueError):app.collect(self.cfg,FakeAPI([],True),[])

    def test_profile_repo_refused(self):
        self.cfg['github']['sources'][0]['repo']='mitsuki-nyann/mitsuki-nyann'
        with self.assertRaises(ValueError):app.score(self.cfg,[])

    def test_source_mode_cannot_double_count(self):
        prior=[event('gh:mitsuki-nyann/example-project:pr:1')]
        with self.assertRaises(ValueError):app.collect(self.cfg,FakeAPI([]),prior)

    def test_merged_pr_only(self):
        self.cfg['github']['sources'][0]['mode']='prs'
        pr={'number':1,'updated_at':'2026-11-23T12:00:00Z','merged_at':'2026-11-23T11:00:00Z',
            'user':{'login':'mitsuki-nyann','type':'User'},'title':'任意の題名',
            'labels':[{'name':'xp:fix'}],'html_url':'https://github.com/example/pull/1'}
        closed={**pr,'number':2,'merged_at':None}
        foreign={**pr,'number':3,'user':{'login':'other'}}
        items=app.collect(self.cfg,FakeAPI([pr,closed,foreign]),[])
        self.assertEqual(len(items),1)
        self.assertEqual(app.score(self.cfg,items)['total_xp'],15)

    def test_pagination_does_not_stop_at_100(self):
        api=app.GitHub()
        with patch.object(api,'get',side_effect=[list(range(100)),[100,101]]) as get:
            self.assertEqual(len(list(api.pages('/example'))),102)
            self.assertEqual(get.call_args.kwargs['page'],2)

    def test_svg_escapes_untrusted_text(self):
        self.cfg['name']='<script>&"'
        self.cfg['trait']='<img src=x onerror=bad>'
        svg=app.render(self.cfg,app.score(self.cfg,[]))
        ET.fromstring(svg)
        self.assertNotIn('<script>',svg)
        self.assertNotIn('<img',svg)

    def test_build_and_demo_keep_actual_ledger_separate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            app.build(root,self.cfg,[])
            app.build(root,self.cfg,app.demo_events(),True)
            self.assertEqual(app.read_json(root/'generated/stats.json')['total_xp'],0)
            self.assertGreater(app.read_json(root/'demo/stats.json')['total_xp'],0)
            self.assertIn('架空の活動',(root/'demo/preview.html').read_text())

    def test_failed_sync_leaves_files_intact(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            app.save(root/'profile.json',app.json_text(self.cfg))
            app.save(root/'data/activities.json','[]\n')
            app.save(root/'data/github.json','[]\n')
            with patch.object(app.GitHub,'get',side_effect=RuntimeError('offline')):
                with self.assertRaises(RuntimeError):app.main(['sync','--root',d])
            self.assertEqual((root/'data/github.json').read_text(),'[]\n')

    def test_add_cli_and_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            app.save(root/'profile.json',app.json_text(self.cfg))
            app.save(root/'data/activities.json','[]\n')
            app.save(root/'data/github.json','[]\n')
            command=['add','--root',d,'--id','manual:practice','--kind','study','--stat','electric','--title','複線図']
            app.main(command)
            self.assertEqual(app.read_json(root/'generated/stats.json')['stats']['electric'],10)
            with self.assertRaises(SystemExit):app.main(command)
            self.assertEqual(len(app.read_json(root/'data/activities.json')),1)


if __name__=='__main__':unittest.main()
