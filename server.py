"""Run: python server.py [--port 8765] [--no-browser] [--sync]."""
import argparse
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import mimetypes
import secrets
import threading
from urllib.parse import parse_qs, urlparse
import webbrowser

import core
import goals
import vocabulary
import profiles
import history

ACTIVE_USER=core.USER_ID

LOCK=threading.Lock()
STATE_LOCK=threading.Lock()
STATE={'running':False,'message':'','done':0,'total':0,'error':None,'version':0}
TOKEN=secrets.token_urlsafe(32)


def progress(**values):
    with STATE_LOCK:STATE.update(values)


def start_sync(gid,goal_id=None,user_id=core.USER_ID,voc_id=None,date_from=None,date_to=None):
    profiles.get(user_id)
    if not LOCK.acquire(blocking=False):raise ValueError('Обновление уже выполняется. Дождитесь завершения.')
    progress(user_id=user_id,running=True,error=None,message='Начинаем обновление…',done=0,total=0)
    def work():
        try:
            if voc_id is not None:
                if goal_id is not None:
                    d=goals.dashboard(goal_id,user_id=user_id)
                    if not any(r['id']==voc_id for r in d['rows']):raise ValueError('Словарь не входит в цель.')
                    start,end=d['period_from'],d['period_to']
                else:start,end=(date_from,date_to) if date_from and date_to else core.period()
                history.sync_vocs([voc_id],start,end,progress,user_id=user_id)
            elif goal_id is not None:goals.sync(goal_id,progress,user_id=user_id)
            else:core.sync(gid,progress,user_id=user_id)
        except Exception as exc:
            progress(error=str(exc),message='Обновление не завершено. Предыдущие данные сохранены.')
        finally:
            with STATE_LOCK:
                STATE['running']=False
                STATE['version']+=1
            LOCK.release()
    threading.Thread(target=work,daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):
        if args and str(args[1] if len(args)>1 else '') not in ('200','202','304'):
            super().log_message(format,*args)

    def send(self,payload,status=200,content_type='application/json; charset=utf-8',extra=None):
        data=json.dumps(payload,ensure_ascii=False).encode() if content_type.startswith('application/json') else payload
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if extra:
            for key,value in extra.items():self.send_header(key,value)
        self.end_headers();self.wfile.write(data)

    def valid_host(self):
        # Loopback binding + Host validation prevents LAN access and DNS rebinding.
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')

    def do_GET(self):
        if not self.valid_host():return self.send({'error':'Invalid host'},403)
        parsed=urlparse(self.path);params=parse_qs(parsed.query)
        try:
            static={'/':'index.html','/app.js':'app.js','/goals-ui.js':'goals-ui.js','/style.css':'style.css','/favicon.svg':'favicon.svg','/details-ui.js':'details-ui.js'}
            if parsed.path in static:
                file=core.ROOT/'static'/static[parsed.path]
                return self.send(file.read_bytes(),content_type=(mimetypes.guess_type(file)[0] or 'application/octet-stream')+'; charset=utf-8')
            if parsed.path=='/api/bootstrap':return self.send({'token':TOKEN,'profile':profiles.get(ACTIVE_USER) if ACTIVE_USER is not None else None})
            if ACTIVE_USER is None and not params.get('profile'):raise ValueError('Сначала укажите свой профиль Клавогонок.')
            user_id=int(params.get('profile',[ACTIVE_USER])[0]);profiles.get(user_id)
            gid=int(params['group'][0]) if params.get('group') else None
            if parsed.path=='/api/data':
                data=core.dashboard(gid,user_id=user_id);data['token']=TOKEN
                return self.send(data)
            if parsed.path=='/api/catalog':return self.send(goals.catalog(user_id=user_id))
            if parsed.path=='/api/goal':return self.send(goals.dashboard(int(params['id'][0]),user_id=user_id))
            if parsed.path=='/api/template':return self.send(goals.definition(int(params['id'][0]),user_id=user_id,template=True))
            if parsed.path=='/api/chart':return self.send(history.chart(int(params['voc'][0]),params['from'][0],params['to'][0],user_id=user_id))
            if parsed.path=='/api/status':
                with STATE_LOCK:state=dict(STATE)
                return self.send(state if state.get('user_id',user_id)==user_id else dict(running=False,message='',done=0,total=0,error=None,version=0))
            if parsed.path=='/api/export':
                if params.get('goal'):
                    data=goals.dashboard(int(params['goal'][0]),user_id=user_id);stream=io.StringIO();writer=csv.writer(stream,delimiter=';')
                    writer.writerow(['Цель','Тип периода','Начало','Окончание','Словарь','ID','Режим','Требуемая скорость','Допуск ошибок','Максимум периода (по загруженным данным)','Лучший результат для цели','Ошибки заезда','Дата результата','Статус','Покрытие полное','Обновлено','Примечание','Краткое имя'])
                    for r in data['rows']:writer.writerow([data['goal']['name'],data['goal']['period_type'],data['period_from'],data['period_to'],r['name'],r['id'],r['mode'],r['speed'],r['max_errors'] if r['mode']=='errors' else '',r['month_max'],r['best_speed'],r['best_errors'],r['best_at'],r['status_label'],r['complete'],r['fetched_at'],r['reason'],r['short_name']])
                    return self.send(stream.getvalue().encode('utf-8-sig'),content_type='text/csv; charset=utf-8',extra={'Content-Disposition':'attachment; filename="klavo-goal.csv"'})
                rows=core.dashboard(gid,user_id=user_id)['rows'];stream=io.StringIO();writer=csv.writer(stream,delimiter=';')
                writer.writerow(['Словарь','Рекорд','Дата рекорда','Максимум за месяц','Дата за месяц','Краткое имя'])
                for row in rows:writer.writerow([row[k] if row[k] is not None else '—' for k in ('name','record','record_date','month_max','month_date','short_name')])
                return self.send(stream.getvalue().encode('utf-8-sig'),content_type='text/csv; charset=utf-8',extra={'Content-Disposition':'attachment; filename="klavo-stats.csv"'})
            self.send({'error':'Not found'},404)
        except ValueError as exc:self.send({'error':str(exc)},400)
        except Exception as exc:self.send({'error':str(exc)},500)

    def do_POST(self):
        global ACTIVE_USER
        if not self.valid_host() or self.headers.get('X-Klavo-Token')!=TOKEN:
            return self.send({'error':'Перезагрузите страницу приложения.'},403)
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):
            return self.send({'error':'Invalid origin'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>256000:raise ValueError('Слишком большой список.')
            body=json.loads(self.rfile.read(length))
            if self.path=='/api/profile/select':
                if not LOCK.acquire(blocking=False):return self.send({'error':'Дождитесь завершения обновления.'},409)
                try:
                    selected=profiles.select(body.get('value',''));ACTIVE_USER=selected['id']
                    return self.send({'profile':selected})
                finally:LOCK.release()
            user_id=int(body.get('profile',ACTIVE_USER));profiles.get(user_id)
            if self.path=='/api/sync':
                gid=int(body['group_id']) if body.get('group_id') is not None else None
                goal_id=int(body['goal_id']) if body.get('goal_id') is not None else None
                start_sync(gid,goal_id,user_id,int(body['voc_id']) if body.get('voc_id') is not None else None,body.get('date_from'),body.get('date_to'))
                return self.send({'started':True},202)
            if self.path=='/api/errors':
                if not LOCK.acquire(blocking=False):return self.send({'error':'Дождитесь завершения обновления.'},409)
                try:return self.send(history.analyze(int(body['voc_id']),body['date_from'],body['date_to'],body.get('limit',10),user_id=user_id))
                finally:LOCK.release()
            if self.path in ('/api/templates/save','/api/templates/delete','/api/groups/save','/api/groups/delete','/api/goals/save','/api/goals/delete','/api/vocabulary/save'):
                if not LOCK.acquire(blocking=False):return self.send({'error':'Дождитесь завершения обновления.'},409)
                try:
                    if self.path=='/api/templates/save':return self.send({'id':goals.save(body,user_id=user_id,template=True)})
                    if self.path=='/api/templates/delete':goals.delete(int(body['id']),user_id=user_id,template=True);return self.send({'deleted':True})
                    if self.path=='/api/vocabulary/save':return self.send(vocabulary.save(body,user_id=user_id))
                    if self.path=='/api/goals/save':return self.send({'id':goals.save(body,user_id=user_id)})
                    if self.path=='/api/goals/delete':goals.delete(int(body['id']),user_id=user_id);return self.send({'deleted':True})
                    if self.path.endswith('/save'):
                        gid=core.save_group(body,user_id=user_id);return self.send({'id':gid})
                    core.delete_group(int(body['id']),user_id=user_id);return self.send({'deleted':True})
                finally:LOCK.release()
            self.send({'error':'Not found'},404)
        except (ValueError,KeyError,TypeError) as exc:self.send({'error':str(exc)},400)
        except Exception as exc:self.send({'error':str(exc)},500)


def main():
    global ACTIVE_USER
    parser=argparse.ArgumentParser(description='KlavoPersonalStat — local personal statistics')
    parser.add_argument('--profile',type=profiles.profile_id,help='Klavogonki profile ID or public profile URL; saved locally')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--sync',action='store_true',help='Refresh statistics and exit')
    args=parser.parse_args();core.init_db();ACTIVE_USER=profiles.select(args.profile)['id'] if args.profile else profiles.active()
    if args.sync:
        if ACTIVE_USER is None:parser.error('Select a profile first: python server.py --profile YOUR_ID --sync')
        core.sync(progress=lambda **state:print(state['message'],flush=True),user_id=ACTIVE_USER);return
    try:server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    except OSError as exc:
        print(f'Cannot start on port {args.port}: {exc}. Choose --port 8766.');return
    url=f'http://127.0.0.1:{args.port}/'
    print(f'KlavoPersonalStat: {url}',flush=True)
    if not args.no_browser:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
