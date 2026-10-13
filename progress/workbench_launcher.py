"""工作台日常启动面板；配置留在本机，服务随面板退出关闭。"""
import argparse
import json
import os
from pathlib import Path
import tempfile
import threading
import webbrowser

import workbench_readonly as ro
from workbench_server import Server
from workbench_store import BookStore

CONFIG = Path(__file__).with_name('workbench_local.json')
DEFAULT_PORT = 7656


def defaults():
    return {'schema_version': 1, 'root': '../../LaTeX_Notes', 'port': DEFAULT_PORT,
            'allow_open': False, 'texstudio': '', 'allow_write': False, 'write_books': [],
            'write_root': '', 'write_book_id': '', 'write_book_ids': {}}


def root_path(value, config_path=CONFIG):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('root不能为空')
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError('root不存在或无法访问') from exc
    if not path.is_dir():
        raise ValueError('root须为目录，不能是文件')
    books = ro.discover(path)
    if not books or any(not any(entry.is_file() for entry in book.glob('*_Content.md')) for book in books):
        raise ValueError('root下无合法书籍入口（须有子目录内的 *_Content.md 登记文件）')
    shelf = path / 'LaTeX_Notes' if (path / 'LaTeX_Notes').is_dir() else path
    for book in books:
        try:
            BookStore(shelf, book.name, request_read=True).navigation()
        except (ValueError, OSError, UnicodeError) as exc:
            raise ValueError(f'书籍登记无效：{book.name}：{exc}') from exc
    return path


def checked(data):
    if not isinstance(data, dict) or set(data) - set(defaults()):
        raise ValueError('配置须为对象且不能含未知字段')
    result = defaults() | data
    if type(result['schema_version']) is not int or result['schema_version'] != 1:
        raise ValueError('配置版本须为1')
    if not isinstance(result['root'], str) or not result['root'].strip():
        raise ValueError('root不能为空')
    if type(result['port']) is not int or not 1 <= result['port'] <= 65535:
        raise ValueError('端口须为1至65535的整数')
    if any(type(result[key]) is not bool for key in ('allow_open', 'allow_write')):
        raise ValueError('权限开关须为布尔值')
    if not isinstance(result['texstudio'], str):
        raise ValueError('TeXstudio路径须为字符串')
    if result['texstudio']:
        executable = Path(result['texstudio'])
        if not executable.is_absolute() or not executable.is_file() or executable.suffix.lower() not in {'.exe', ''}:
            raise ValueError('TeXstudio须为现有可执行文件的绝对路径')
    if not isinstance(result['write_books'], list) or any(not isinstance(x, str) or not x.strip() for x in result['write_books']):
        raise ValueError('write_books须为书名字符串列表')
    if any(not isinstance(result[key], str) for key in ('write_root', 'write_book_id')):
        raise ValueError('保存许可根与永久ID须为字符串')
    ids = result['write_book_ids']
    if not isinstance(ids, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in ids.items()):
        raise ValueError('逐书永久ID须为书名到UUID的对象')
    return result


def write_permission(data, config_path=CONFIG):
    """缺少完整许可即保持只读；完整许可失配时拒绝启动。"""
    data = checked(data)
    if not data['allow_write'] or not data['write_books']:
        return False, ()
    ids = data['write_book_ids'] or ({'General_Topology': data['write_book_id']} if data['write_book_id'] else {})
    if not data['write_root'] or not ids:
        return False, ()
    if len(set(data['write_books'])) != len(data['write_books']) or set(ids) != set(data['write_books']):
        raise ValueError('每本许可书必须独立绑定永久ID')
    root = root_path(data['root'], config_path)
    shelf = root / 'LaTeX_Notes' if (root / 'LaTeX_Notes').is_dir() else root
    permitted = Path(data['write_root'])
    if not permitted.is_absolute() or shelf.resolve() != permitted.resolve(strict=True):
        raise ValueError('保存许可根失配，请重新明确确认')
    known = {p.name for p in ro.discover(root)}
    if set(ids) - known or len(set(ids.values())) != len(ids):
        raise ValueError('许可书未登记或永久ID重复，禁止别名继承许可')
    for name, expected in ids.items():
        book = (shelf / name).resolve(strict=True)
        if book.parent != shelf.resolve():
            raise ValueError('许可书越过根目录')
        if BookStore(shelf, name).identity()['book_id'] != expected:
            raise ValueError(f'{name}永久ID失配，请重新明确确认')
    return True, tuple(data['write_books'])


def grant_books(data, identities, config_path=CONFIG):
    if not isinstance(identities, dict) or not identities:
        raise ValueError('许可须为非空书名到永久ID对象')
    root = root_path(data['root'], config_path)
    shelf = root / 'LaTeX_Notes' if (root / 'LaTeX_Notes').is_dir() else root
    updated = data | {'allow_write': True, 'write_books': list(identities),
                      'write_root': str(shelf.resolve()), 'write_book_id': '',
                      'write_book_ids': dict(identities)}
    write_permission(updated, config_path)
    return updated


def grant_gt(data, expected_id, config_path=CONFIG):
    import uuid
    try:
        if str(uuid.UUID(expected_id)) != expected_id:
            raise ValueError('永久ID须为规范UUID')
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('永久ID须为规范UUID') from exc
    root = root_path(data['root'], config_path)
    shelf = root / 'LaTeX_Notes' if (root / 'LaTeX_Notes').is_dir() else root
    updated = data | {'allow_write': True, 'write_books': ['General_Topology'],
                      'write_root': str(shelf.resolve()), 'write_book_id': expected_id, 'write_book_ids': {}}
    write_permission(updated, config_path)
    return updated


def load_config(path=CONFIG):
    if not path.exists():
        return defaults()
    try:
        return checked(json.loads(path.read_text(encoding='utf-8-sig')))
    except (OSError, ValueError) as exc:
        raise ValueError(f'本机配置读取失败：{exc}；原文件保留，请修复后重试：{path}') from exc


def save_config(data, path=CONFIG):
    data = checked(data)
    root_path(data['root'], path)
    write_permission(data, path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=path.parent, prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def change_root(data, value, path=CONFIG):
    resolved = root_path(value, path)
    current = Path(data['root']).expanduser()
    if not current.is_absolute():
        current = path.parent / current
    updated = data | {'root': str(resolved)}
    if resolved != current.resolve():
        updated.update(allow_write=False, write_books=[], write_root='', write_book_id='', write_book_ids={}, allow_open=False)
    return updated


class Session:
    """仅管理本面板创建的服务，端口占用时不接管任何服务。"""
    def __init__(self):
        self.server = None
        self.thread = None

    def start(self, data, config_path=CONFIG, no_browser=False):
        if self.server is not None:
            raise ValueError('本面板服务已启动；配置变更前请先停止')
        root = root_path(data['root'], config_path)
        allow_write, books = write_permission(data, config_path)
        server = Server(root, data['port'], allow_write, books, allow_open=data['allow_open'],
                        texstudio=data['texstudio'] or None)
        permission = dict(data)
        server.write_validator = lambda: write_permission(permission, config_path)
        thread = threading.Thread(target=server.serve_forever, name='workbench-http', daemon=True)
        try:
            thread.start()
        except BaseException:
            server.server_close()
            raise
        self.server, self.thread = server, thread
        print(f"已启动：{server.origin}；{'许可书可保存：' + ', '.join(books) if allow_write else '只读'}；退出本面板会停止服务。")
        if not no_browser:
            try:
                webbrowser.open(server.origin)
            except OSError as exc:
                print(f'浏览器打开失败，可手动访问上方地址：{exc}')
        return server.origin

    def stop(self):
        if self.server is not None:
            try:
                self.server.shutdown()
            finally:
                self.server.server_close()
                self.thread.join()
                self.server = self.thread = None


def panel(config_path=CONFIG, no_browser=False):
    try:
        data = load_config(config_path)
    except ValueError as exc:
        print(exc)
        return 2
    session = Session()
    try:
        while True:
            print('\n写作工作台启动配置（默认只读；逐书永久ID独立授权）')
            print(f"root：{data['root']}（相对路径以配置文件目录为基准）")
            print(f"端口：{data['port']}；allow-open：{data['allow_open']}；TeXstudio：{data['texstudio'] or '自动查找'}")
            print(f"保存配置：{data['allow_write']}；许可书：{', '.join(data['write_books']) or '无'}；许可根：{data['write_root'] or '无'}；永久ID：{data['write_book_ids'] or data['write_book_id'] or '无'}")
            print(f"服务：{session.server.origin if session.server else '未启动'}；实际写入：{', '.join(sorted(session.server.write_books)) if session.server and session.server.allow_write else '禁用'}")
            if session.server:
                print(f'当前服务root：{session.server.root}；当前端口：{session.server.server_port}；当前allow-open：{session.server.allow_open}')
            print('配置在下次显式启动生效；服务运行期间须先停止再修改。')
            print('1. 设置根目录  2. 设置端口  3. 切换allow-open  4. 设置TeXstudio路径')
            print('5. 启动服务  6. 停止本面板服务  7. 逐书独立保存许可  0. 返回（停止本面板服务）')
            try:
                choice = input('选择：').strip()
                if choice in {'', '0', '6'} and session.server is not None:
                    confirmation = input('停止服务前请保存网页中尚未保存的输入；已保存并确认停止？输入 y 确认，其余取消：').strip().lower()
                    if confirmation != 'y':
                        print('已取消停止，服务继续运行。')
                        continue
                if choice in {'', '0'}:
                    break
                if choice == '5':
                    session.start(data, config_path, no_browser)
                    continue
                if choice == '6':
                    session.stop()
                    print('本面板服务已停止。')
                    continue
                if choice not in {'1', '2', '3', '4', '7'}:
                    print('请选择0至7。')
                    continue
                if session.server is not None:
                    raise ValueError('修改配置前请先选择6停止本面板服务')
                updated = dict(data)
                if choice == '1':
                    updated = change_root(data, input('根目录（工作区或LaTeX_Notes目录）：').strip(), config_path)
                elif choice == '2':
                    try:
                        updated['port'] = int(input('端口（1至65535）：').strip())
                    except ValueError as exc:
                        raise ValueError('端口须为1至65535的整数') from exc
                elif choice == '3':
                    updated['allow_open'] = not data['allow_open']
                elif choice == '7':
                    if data['allow_write']:
                        updated.update(allow_write=False, write_books=[], write_root='', write_book_id='', write_book_ids={})
                    else:
                        print('仅许可当前根内已初始化书；不初始化、不迁移、不修改审核结论。allow-open不变。')
                        identity = input('输入书名=已核实永久ID的JSON对象；或单个GT永久ID：').strip()
                        if identity.startswith('{'):
                            updated = grant_books(data, json.loads(identity), config_path)
                            confirmation = 'SAVE'
                        else:
                            updated = grant_gt(data, identity, config_path)
                            confirmation = 'GT'
                        if input(f"许可根 {updated['write_root']}，许可书 {updated['write_books']}；输入 {confirmation} 确认：").strip() != confirmation:
                            print('已取消授权。')
                            continue
                else:
                    value = input('TeXstudio可执行文件绝对路径（回车恢复自动查找）：').strip()
                    if value and (not Path(value).is_absolute() or not Path(value).is_file()):
                        raise ValueError('TeXstudio须为现有文件的绝对路径')
                    updated['texstudio'] = value
                save_config(updated, config_path)
                data = updated
                print('本机配置已保存。root改变会清空原写白名单及权限。')
            except (ValueError, OSError) as exc:
                print(f'操作失败：{exc}；若端口已占用，请另选端口；不会停止或复用现有服务。')
    except (EOFError, KeyboardInterrupt):
        print('\n输入结束或中断：服务随面板退出而停止；网页未保存输入不自动保存。')
    finally:
        session.stop()
    return 0


def main():
    parser = argparse.ArgumentParser(description='工作台日常启动配置面板，默认只读，逐书永久ID保存许可')
    parser.add_argument('--config', type=Path, default=CONFIG, help='本机配置JSON；相对root以该文件目录为基准')
    parser.add_argument('--no-browser', action='store_true', help='启动服务时不自动打开浏览器')
    args = parser.parse_args()
    return panel(args.config.resolve(), args.no_browser)


if __name__ == '__main__':
    raise SystemExit(main())
