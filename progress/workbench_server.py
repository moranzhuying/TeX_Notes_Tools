"""独立回环HTTP；默认只读，书白名单和页面确认均不可省略。"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser

import workbench_readonly as ro
import workbench_features as features
import workbench_pdf as pdf
import workbench_daily as daily
from workbench_store import BookStore, Conflict, StoreError, HASH

LIMIT = 65536


class InputError(ValueError):
    pass


class Denied(ValueError):
    pass


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root, port=0, allow_write=False, write_books=(), *, allow_open=False, texstudio=None):
        self.root = Path(root).resolve(strict=True)
        self.shelf = self.root / 'LaTeX_Notes' if (self.root / 'LaTeX_Notes').is_dir() else self.root
        self.allow_open = allow_open
        self.open_lock = threading.RLock()
        self.texstudio = pdf.executable(texstudio, 'texstudio') if texstudio else None
        self.allow_write = allow_write
        self.write_books = set(write_books)
        self.token = secrets.token_urlsafe(32)
        self.session_id = secrets.token_hex(16)
        self.changes = daily.Changes(self.root, ro.discover)
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)
        self.host = '127.0.0.1:' + str(self.server_port)
        known = {p.name for p in ro.discover(self.root)}
        if self.write_books - known or (self.write_books and not allow_write):
            self.server_close()
            raise InputError('写白名单须为已登记书名且同时指定--allow-write')

    def effective_permission(self):
        validator = getattr(self, 'write_validator', None)
        if validator is None:
            return self.allow_write, self.write_books
        try:
            allowed, books = validator()
            return allowed, set(books)
        except (ValueError, OSError):
            return False, set()

    def catalog(self):
        allowed, books = self.effective_permission()
        data = ro.scan(self.root)
        data['audit_completed'] = True
        data['audit_scope'] = '全量现行登记绑定扫描；不代表数学审核、原书目录核定或已保存版本依据核验'
        data['readonly'] = not allowed
        data['write_books'] = sorted(books)
        data['states'] = {k: sorted(v) for k, v in ro.KNOWN.items()}
        for book in data['books']:
            store = BookStore(self.shelf, book['name'])
            book['initialized'] = store.path('Materials/workbench/book.json').is_file()
            book['writable'] = allowed and book['name'] in books
            book['scopes'] = sorted(store._scopes(store._catalog()))
        return data

    def navigation(self):
        allowed, permitted = self.effective_permission()
        books = []
        for path in ro.discover(self.root):
            book = BookStore(self.shelf, path.name).navigation()
            book['writable'] = allowed and path.name in permitted
            books.append(book)
        return {'schema_version': 1, 'audit_completed': False,
                'audit_scope': '轻量登记导航；未全量核验TeX、record、资料或版本依据',
                'readonly': not allowed, 'write_books': sorted(permitted),
                'allow_open': self.allow_open,
                'states': {k: sorted(v) for k, v in ro.KNOWN.items()}, 'books': books}

    def store(self, name, *, request_read=False):
        if not isinstance(name, str) or name not in {p.name for p in ro.discover(self.root)}:
            raise InputError('未知书或越界书名')
        return BookStore(self.shelf, name, request_read=request_read)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_):
        pass

    def reply(self, status, data, html=False):
        payload = data.encode('utf-8') if html else json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'")
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def guard(self, post=False):
        if self.headers.get_all('Host') != [self.server.host]:
            raise Denied('Host不匹配')
        origins = self.headers.get_all('Origin') or []
        if (post and origins != [self.server.origin]) or (origins and origins != [self.server.origin]):
            raise Denied('Origin不匹配')
        if post and self.headers.get_all('X-Workbench-CSRF') != [self.server.token]:
            raise Denied('CSRF验证失败')

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self, post):
        try:
            self.guard(post)
            url = urlsplit(self.path)
            if url.scheme or url.netloc or url.fragment:
                raise InputError('请求路径不合法')
            if not post and url.path == '/' and not url.query:
                page = Path(__file__).with_name('workbench_editor.html').read_text(encoding='utf-8')
                return self.reply(200, page.replace('__CSRF__', self.server.token), True)
            if not post and url.path == '/session' and not url.query:
                allowed, permitted = self.server.effective_permission()
                return self.reply(200, {'service': 'latex-writing-workbench', 'schema_version': 1,
                    'session_id': self.server.session_id, 'root': str(self.server.root), 'port': self.server.server_port,
                    'allow_open': self.server.allow_open, 'allow_write': allowed,
                    'write_books': sorted(permitted), 'texstudio': self.server.texstudio})
            if not post and url.path == '/navigation' and not url.query:
                return self.reply(200, self.server.navigation())
            if not post and url.path == '/data' and not url.query:
                return self.reply(200, self.server.catalog())
            if post:
                if url.query:
                    raise InputError('POST不接受query')
                if self.headers.get_all('Content-Type') != ['application/json'] or self.headers.get('Transfer-Encoding'):
                    raise InputError('须为定长application/json')
                lengths = self.headers.get_all('Content-Length') or []
                if len(lengths) != 1 or len(lengths[0]) > 10 or not lengths[0].isascii() or not lengths[0].isdigit():
                    raise InputError('请求长度不合法或过长')
                length = int(lengths[0])
                if not 0 < length <= LIMIT:
                    # 小幅超限先有限消费，避免Windows未读请求体导致RST吞掉400；不解析或接受超限JSON。
                    if LIMIT < length <= LIMIT + 1024:
                        self.rfile.read(length)
                    raise InputError('请求长度不合法或过长')
                raw = self.rfile.read(int(lengths[0]))
                if len(raw) != int(lengths[0]):
                    raise InputError('请求不完整')
                try:
                    args = json.loads(raw)
                except (ValueError, UnicodeError) as exc:
                    raise InputError('JSON无效') from exc
                if not isinstance(args, dict):
                    raise InputError('JSON须为对象')
            else:
                query = parse_qs(url.query, keep_blank_values=True)
                if any(len(v) != 1 for v in query.values()):
                    raise InputError('重复query')
                args = {k: v[0] for k, v in query.items()}
            if not post and url.path == '/changes':
                if set(args) not in ({'since'}, {'since', 'force'}):
                    raise InputError('字段缺失或多余')
                if 'force' in args and args['force'] != '1':
                    raise InputError('force只接受1，省略时使用短期缓存')
                return self.reply(200, self.server.changes.read(args['since'], force='force' in args))
            if not post and url.path == '/participation':
                if set(args) != {'book', 'unit'}:
                    raise InputError('字段缺失或多余')
                return self.reply(200, daily.participation(self.server.store(args['book'], request_read=True), args['unit']))
            if not post and url.path == '/api/pdfcontent':
                if set(args) != {'book', 'offset', 'stamp'}:
                    raise InputError('字段缺失或多余')
                if self.headers.get('Sec-Fetch-Site') not in {None, 'same-origin', 'none'}:
                    raise Denied('须为同源读取')
                store = self.server.store(args['book'], request_read=True)
                return self.reply(200, pdf.content(store, args['offset'], args['stamp']))
            extra_reads = {'/aggregate': {'book'}, '/stats': {'book'}, '/issues': {'book'},
                           '/report': {'book'}, '/pdf': {'book'}, '/pdfinfo': {'book'}, '/pdfpage': {'book', 'q'}}
            if not post and url.path in extra_reads:
                if set(args) != extra_reads[url.path]:
                    raise InputError('字段缺失或多余')
                if url.path in {'/aggregate', '/stats', '/issues', '/report'}:
                    result = features.aggregate(self.server, args['book'])
                    if url.path == '/report':
                        payload = features.markdown(result).encode('utf-8')
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/markdown; charset=utf-8')
                        self.send_header('Content-Disposition', 'attachment; filename="workbench-report.md"')
                        self.send_header('Content-Length', str(len(payload)))
                        self.send_header('Cache-Control', 'no-store')
                        self.send_header('X-Content-Type-Options', 'nosniff')
                        self.send_header('Connection', 'close')
                        self.end_headers()
                        self.wfile.write(payload)
                        self.close_connection = True
                        return
                else:
                    store = self.server.store(args['book'], request_read=True)
                    if url.path == '/pdf':
                        return pdf.serve(self, store)
                    result = pdf.locate(store, args['q']) if url.path == '/pdfpage' else pdf.info(store)
                return self.reply(200, result)
            if post and url.path == '/open':
                if set(args) not in ({'book', 'unit', 'confirm'}, {'book', 'unit', 'confirm', 'line', 'path', 'expected'}):
                    raise InputError('字段缺失或多余')
                if not self.server.allow_open:
                    raise Denied('OS打开默认禁用；须显式启动--allow-open，此开关不授权TeX写入')
                store = self.server.store(args['book'], request_read=True)
                return self.reply(200, pdf.open_tex(self.server, store, args['unit'], args['confirm'], args.get('line'), args.get('path'), args.get('expected')))
            if not post and url.path in {'/search', '/source'}:
                required = {'q', 'book', 'limit'} if url.path == '/search' else {'book', 'unit', 'line'}
                if set(args) != required:
                    raise InputError('字段缺失或多余')
                if url.path == '/search':
                    result = features.search(self.server, args['q'], args['book'], args['limit'])
                else:
                    result = features.source(self.server.store(args['book'], request_read=True), args['unit'], args['line'])
                return self.reply(200, result)
            schemas = {'/review': {'book', 'unit'}, '/runtime': {'book'}, '/summary': {'book', 'scope'}, '/backups': {'book'},
                       '/init': {'book', 'confirm'}, '/patch-review': {'book', 'unit', 'patch', 'expected'},
                       '/patch-runtime': {'book', 'patch', 'expected', 'revision'}, '/create-summaries': {'book', 'confirm'},
                       '/patch-summary': {'book', 'scope', 'patch', 'expected'}, '/restore': {'book', 'backup_id', 'expected', 'confirm'}}
            reads = {'/review', '/runtime', '/summary', '/backups'}
            if url.path not in schemas or (url.path in reads) == post:
                return self.reply(404, {'error': '接口不存在'})
            if set(args) != schemas[url.path]:
                raise InputError('字段缺失或多余')
            store = self.server.store(args['book'], request_read=not post)
            initialized = store.path('Materials/workbench/book.json').is_file()
            minimal = not post and not initialized
            ids = store.registered_ids() if minimal and ('unit' in args or 'scope' in args) else None
            if 'unit' in args:
                if not isinstance(args['unit'], str):
                    raise InputError('unit须为字符串')
                if minimal:
                    if args['unit'] not in ids:
                        raise InputError('单位未登记')
                else:
                    store._unit(args['unit'])
            if 'scope' in args and (not isinstance(args['scope'], str) or args['scope'] not in store._scopes(ids if minimal else store._catalog())):
                raise InputError('未知总结范围')
            if post:
                if not self.server.allow_write or args['book'] not in self.server.write_books:
                    raise Denied('本书未授权写入')
                validator = getattr(self.server, 'write_validator', None)
                if validator is not None:
                    try:
                        allowed, books = validator()
                        if not allowed or args['book'] not in books:
                            raise ValueError('保存许可已失效')
                    except (ValueError, OSError) as exc:
                        raise Denied(f'保存许可核验失败：{exc}') from exc
                if 'confirm' in args and args['confirm'] is not True:
                    raise InputError('必须显式确认')
                if 'expected' in args and (not isinstance(args['expected'], str) or not HASH.fullmatch(args['expected'])):
                    raise InputError('expected须为完整SHA256')
                if 'patch' in args and not isinstance(args['patch'], dict):
                    raise InputError('patch须为对象')
                if 'revision' in args and type(args['revision']) is not int:
                    raise InputError('revision须为整数')
                if url.path == '/init':
                    result = store.init()
                elif url.path == '/create-summaries':
                    result = store.create_summaries()
                elif url.path == '/patch-review':
                    result = store.patch_review(args['unit'], args['patch'], args['expected'])
                elif url.path == '/patch-runtime':
                    result = store.patch_runtime(args['patch'], args['expected'], args['revision'])
                elif url.path == '/patch-summary':
                    result = store.patch_summary(args['scope'], args['patch'], args['expected'])
                else:
                    result = store.restore(args['backup_id'], args['expected'])
            elif url.path == '/review':
                result = store.read_review(args['unit'])
            elif not store.path('Materials/workbench/book.json').is_file():
                result = {'initialized': False}
            elif url.path == '/runtime':
                result = store.read_runtime()
            elif url.path == '/summary':
                result = store.read_summary(args['scope']) if store.path('Materials/workbench/summaries.md').is_file() else {'missing': True}
            else:
                result = store.list_backups()
            self.reply(200, result)
        except (ConnectionError, BrokenPipeError):
            # 页面关闭或取消请求后连接已断开，不再尝试向同一连接发送错误响应。
            self.close_connection = True
        except Denied as exc:
            self.reply(403, {'error': str(exc)})
        except Conflict as exc:
            self.reply(409, {'error': str(exc)})
        except (InputError, StoreError) as exc:
            # 替换后读回失败是持久化故障，而不是输入错误。
            self.reply(500 if '替换后核对失败' in str(exc) else 400, {'error': str(exc)})
        except Exception:
            self.reply(500, {'error': '读取或持久化失败；勿视为保存成功，请重新读取核对'})


def main():
    parser = argparse.ArgumentParser(description='独立本地工作台，默认只读；退出仅用CLI中断')
    parser.add_argument('--root', required=True)
    parser.add_argument('--port', type=int, default=7656)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--allow-write', action='store_true')
    parser.add_argument('--write-book', action='append', default=[])
    parser.add_argument('--allow-open', action='store_true', help='独立授权确认后调起TeXstudio，不授权TeX写入')
    parser.add_argument('--texstudio', help='现有TeXstudio可执行文件的绝对路径')
    args = parser.parse_args()
    try:
        server = Server(args.root, args.port, args.allow_write, args.write_book, allow_open=args.allow_open, texstudio=args.texstudio)
    except (ValueError, OSError) as exc:
        parser.exit(2, str(exc) + '\n')
    print(server.origin + '（默认只读或仅指定白名单；Ctrl+C退出）', flush=True)
    if not args.no_browser:
        webbrowser.open(server.origin)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
