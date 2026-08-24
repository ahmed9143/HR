import os, tempfile, shutil
os.environ['HR_DATA_DIR']=os.path.join(tempfile.gettempdir(),'hr_v10_test')
shutil.rmtree(os.environ['HR_DATA_DIR'],ignore_errors=True)
import server
server.init()
# strict validation: duplicate code, invalid national id
rows=[{'emp_code':'1001','name':'Ahmed Mohamed','national_id':'123','department':'Nursing','job':'Nurse'}, {'emp_code':'1001','name':'Ahmed 2','national_id':'12345678901234','department':'Nursing','job':'Nurse'}]
clean,errors=server.v10_validate_records(rows)
assert errors, 'validation should catch errors'
# seed evaluation intelligence
c=server.db()
for code,name,score in [('E1','A',95),('E2','B',74),('E3','C',73),('E4','D',70)]:
    c.execute('INSERT INTO employees(emp_code,name,department,unit,job,status) VALUES(?,?,?,?,?,?)',(code,name,'Nursing','Unit 1','Nurse','على رأس العمل'))
    c.execute('INSERT INTO employee_evaluations(emp_code,period,score,created_at) VALUES(?,?,?,?)',(code,'2026-08',score,server.now()))
c.commit(); c.close()
stats=server.v10_evaluation_engine('2026-08')
print(stats); assert any(x[3]=='HIGH' for x in stats), 'evaluation anomaly engine failed'
server.v10_alerts_engine()
c=server.db();
for t in ('alert_rules','evaluation_stats','device_events','workflow_items','branding_profiles','mapping_templates','match_decisions','payroll_periods','sync_queue','security_events'):
    assert c.execute('select 1 from sqlite_master where type="table" and name=?',(t,)).fetchone(), t
c.close()
print('V10 COMPLETE TESTS: PASS')
