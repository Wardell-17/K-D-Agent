# bottle.py 架构逆向分析

> 分析对象：`bottle.py`（单文件 Web 框架，共 175882 字符 / 4584 行）
> 声明：本文所有结论均基于对源文件逐段真实阅读（含 10 万字符之后的后段）与符号/行号定位，非臆测。符号名均标注其在文件中的起始字符位置（`@offset`）。

---

## 1. 核心类清单与职责

### 1.1 应用对象：`Bottle`（@7467）
- 一个 `Bottle` 实例在框架中即代表一个完整的、独立的 Web 应用（路由集合、回调、插件、资源与配置）。
- 构造器（`__init__` @5625，实际在 class Bottle 体内）：
  - `self.config = self._global_config._make_overlay()` —— 应用配置，继承自类级全局 `ConfigDict`（惰性属性 `_global_config`），通过 overlay 机制隔离。
  - `self.routes = []` —— 已安装的 `Route` 实例列表。
  - `self.router = Router()` —— 将请求映射到 `Route` 的核心路由表（见第 2 节）。
  - `self.error_handler = {}` —— 错误状态码→错误处理函数 的映射。
  - `self.plugins = []` —— 已安装插件；构造时默认安装 `JSONPlugin()` 与 `TemplatePlugin()`。
  - `self._mounts = []`、`self.resources = ResourceManager()`（静态资源检索）。
- 钩子机制：`add_hook / trigger_hook` 支持 `before_request`、`after_request`、`app_reset`、`config` 四类钩子（`__hook_names`），`after_request` 为逆序触发。
- 挂载复用：`_mount_wsgi` (@26346) 可将任意 WSGI 应用挂载到某前缀，通过生成一个 `mountpoint_wrapper` 回调并以 `PROXY` 方法 + `method='PROXY'` 注册路由实现。

### 1.2 请求/响应封装
- **`BaseRequest`**（@44328）：WSGI environ 字典的封装，提供大量只读属性：`path`、`method`、`headers`（`WSGIHeaderDict`）、`cookies`、`query`、`forms`、`params`、`files`、`json`、`POST`、`body`、`url` 等。`POST` 使用 `_MultipartParser` 解析 multipart，文件字段被包装为 `FileUpload`（见第 3 节）。
  - **`LocalRequest(BaseRequest)`**（@76054）：线程本地版本；`bind = BaseRequest.__init__`、`environ = _local_property()`（thread-local）。模块级全局 `request = LocalRequest()`，保证多线程下每个线程取到自己的当前请求。
- **`BaseResponse`**（@64171）：响应体 + 头 + cookie 的存储类。支持大小写无关的 dict 式头访问；`_wsgi_status_line()` / `headerlist` 生成 WSGI 兼容的状态行与 (name,value) 头元组列表（含 status 码对非法头去重 `bad_headers`，以及 Set-Cookie 序列化）。
  - **`LocalResponse(BaseResponse)`**（@76504）：线程本地版本；各属性为 `_local_property()`。模块级全局 `response = LocalResponse()`。
- **`HTTPResponse(Response, BottleException)`**（@77101）：可被 handler raise 或 return 以短路请求处理，直接覆盖全局 `response` 状态（`apply(other)` 拷贝状态）；**不**触发错误处理器。
  - **`HTTPError(HTTPResponse)`**（@77660 附近）：附 `exception` / `traceback` 字段，raise/返回它时才**触发**错误处理器（`default_status=500`）。

### 1.3 路由系统
- **`Router`**（@7915）：有序的 路由规则→目标 集合，负责编译 URL 规则并在请求到来时匹配（详见第 2 节）。
- **`Route`**（@7810）：包装一个路由回调及其元数据/配置，并按需应用插件。
  - `call` 缓存属性（`@cached_property`）：把回调经 `/src/app/plugins/all_plugins()` + `_make_callback()` 包装后的"终版可调用对象"，首次访问后缓存。
  - `get_callback_args()` 返回回调可接受的关键字参数名（用于 URL 参数注入，见第 3 节生命周期）。

### 1.4 其它支撑类
- **`ConfigDict`**（@89045）：dict 风格的配置存储，支持 namespace、validator、meta 与 overlay 继承（`_make_overlay`/`_set_virtual`），用于 app/route 配置。
- **`AppStack(list)`**（@98295）：栈式 list；调用它返回栈顶默认应用。`push()` 创建新 `Bottle`，`default` 属性返回栈顶（空则 push）。模块末尾 `apps = app = default_app = AppStack()` 建立默认应用栈。
- **`ResourceManager`**（@101200 附近）：路径检索/打开应用资源文件。
- 数据容器：`MultiDict`、`FormsDict`、`HeaderDict`、`WSGIHeaderDict`。
- `WSGIFileWrapper`：将文件对象包装为可迭代的 WSGI body。
- 插件：`JSONPlugin`（dict→json 自动序列化）、`TemplatePlugin`（为带 template 配置的路由套 `view` 装饰器）。
- `FileUpload`（@103482，10 万字符之后）：见第 3 节详述。

---

## 2. 路由匹配机制

### 2.1 URL 规则如何被编译（`Router.add` @~9000）
1. **词法切分规则**：`Router.rule_syntax` 正则贪婪地识别通配符 `<name>` 与旧式 `:name`，`_itertokens(rule)` 将其切分为 (key, mode, conf) 序列。
2. **过滤/类型转换**：内置 `self.filters` 字典定义了 4 种通配符过滤器，每个过滤器返回 `(regexp, to_python, to_url)` 三元组：
   - `'re'`：默认 `[^/]+`
   - `'int'`：`r'-?\d+'` + int 转换
   - `'float'`：`r'-?[\d.]+'`
   - `'path'`：`r'.+?'`
   - 用户可用 `add_filter(name, func)` 扩展。
3. **规则编译**：
   - **静态规则**（无通配符）：存入 `self.static[method][自建路径] = (target, None)`（`strict_order=False` 时静态优先）。
   - **动态规则**：将每段通配符替换为 `(?P<key>regexp)`，把整条 rule 拼接成正则 `^(pattern)$` 并 `re.compile`；随后 `_compile(method)` 把属于同一 HTTP 方法的若干动态规则**合并**成若干条组合正则（每 $99$ 条规则一组，受 `_MAX_GROUPS_PER_PATTERN` 限制），存入 `self.dyna_regexes[method]`。`.match(path)` 后依据捕获组 `match.lastindex` 反查具体 `(target, getargs)`。
   - `getargs(path)`：从 `match.groupdict()` 提取 URL 参数，按通配符过滤器做类型转换（转换失败抛 `HTTPError(400)`），并剔除匿名通配符 `anonN`。
4. **URL 反向构建**：`build(_name, *anons, **query)` 依据 `self.builder` 中的 (name, out_filter or str, string) 序列填充通配符生成 URL；`bottle.route` 可给规则命名，路由会以名称建 URL。

### 2.2 请求到来如何找到处理函数（`Router.match` @15702）
```
verb = environ['REQUEST_METHOD'].upper()
path = environ['PATH_INFO'] or '/'
methods = ('PROXY','HEAD','GET','ANY') if verb=='HEAD' else ('PROXY',verb,'ANY')
for method in methods:
    静态: 查 self.static[method][path]
    动态: 对 self.dyna_regexes[method] 内每条组合正则 combined(path)
         命中则 (target, getargs) = rules[match.lastindex-1]
```
- 命中即返回 `(target, getargs)`（以**注册顺序**匹配，是"第一个满足的 route"）。
- 无命中但存在其它方法的同路径匹配 → 抛 `HTTPError(405, "Method not allowed.", Allow=...)`（带 Allow 头）。
- 完全无匹配 → 抛 `HTTPError(404, "Not found: ...")`。
- `default_filter='re'`，而 `HEAD` 请求会自动尝试 `GET` 方法规则（methods 元组中带 `GET`），`PROXY` 用于挂载的 WSGI 子应用。

---

## 3. 请求生命周期（WSGI 入口 → 用户回调 → 响应）

### 3.1 入口
- `Bottle` 是可调用 WSGI 应用：`__call__(environ, start_response)` → `return self.wsgi(environ, start_response)`（@41999，class Bottle 内 `wsgi` 方法）。

### 3.2 `Bottle.wsgi(environ, start_response)` 主流程
1. 调用 `self._handle(environ)` 得到 `out`。
2. `out = self._cast(out)` 把产物转换为 WSGI 兼容的字节迭代体（见下）。
3. 依据响应状态码/RFC2616 处理空响应（100/101/204/304 或 HEAD 请求清空 body）。
4. 从 `environ.pop('bottle.exc_info', None)` 取异常信息，调用 `start_response(response._wsgi_status_line(), response.headerlist, exc_info)` 并返回 `out` 迭代器。
5. catchall 下若抛出致命异常，生成 HTML 错误页并 `start_response('500 INTERNAL SERVER ERROR', ...)`。

### 3.3 `Bottle._handle(environ)` 核心链路（@37406）
1. 记录 `environ['bottle.raw_path'] = environ['PATH_INFO']` 并用 `_wsgi_recode(path)` 重编码 `PATH_INFO`；写入 `bottle.app`。
2. **绑定上下文**：`request.bind(environ)`（即 `BaseRequest.__init__`，把 environ 挂到线程本地的 `request`）与 `response.bind()`。此后代码中的全局 `request`/`response` 即代表当前请求/响应。
3. 触发 `before_request` 钩子。
4. `route, args = self.router.match(environ)` → 写入 `environ['bottle.route']`、`route.url_args`。
5. `out = route.call(**args)` —— 调用经插件包装、缓存的回调，并把 `router.match` 返回的 URL 通配符参数按关键字注入回调（与 `Route.get_callback_args()` 的签名匹配）。
6. 若回调 raise/返回 `HTTPResponse`（含 `HTTPError`），`except HTTPResponse` 捕获并赋值给 `out`；`finally` 中 `out.apply(response)` 把状态写回全局 response，并触发 `after_request` 钩子。
7. 异常处理：`KeyboardInterrupt/SystemExit/MemoryError` 直接重抛；其它异常在 `catchall=True` 时包装为 `HTTPError(500, ...)`（写入 `wsgi.errors` 与 `bottle.exc_info`）；否则重抛。

### 3.4 `_cast` 类型归一（@38200 附近）
把 `out` 归一为 WSGI body 迭代：
- 空 → `[]`（并补 `Content-Length: 0`）。
- `str` → 用 `response.charset` 编码；`bytes` → 直接返回并设置 Content-Length。
- `HTTPError` → `apply` 后交给 `self.error_handler` 或默认错误页处理，递归 `_cast`；
- `HTTPResponse` → `apply` 后 `_cast(body)`。
- 文件类（有 `read`）→ 优先用 `wsgi.file_wrapper`，否则 `WSGIFileWrapper`。
- 其它可迭代/generator → peek 首元素类型，bytes 直接链、str 逐个编码，`close` 回调用 `_closeiter` 挂到迭代器上。

### 3.5 `FileUpload`（@103482，位于 10 万字符之后）
- 描述：`multipart/form-data` 上传的**单个文件**包装。`POST` 解析时（见 `BaseRequest.POST`）对 multipart 中带 `filename` 的 part 构造 `FileUpload(part.file, part.name, part.filename, part.headerlist)`。独立文件不会进 `forms`，只进 `files`。
- 属性：
  - `file`：底层文件对象（BytesIO 缓冲或临时文件，取决于是否超 `MEMFILE_MAX`）。
  - `name`：表单字段名。
  - `raw_filename`：客户端原始文件名（可能不安全）。
  - `headers`：该 part 的 `HeaderDict`（如 Content-Type）。
  - `content_type` / `content_length`：`HeaderProperty` 别名。
- `filename`（`@cached_property`）：对 `raw_filename` 做安全归一化——Unicode NFKD 规范化、去重音/非 ASCII、取 basename、只保留 `[a-zA-Z0-9-_.\s]`、空白/连字符合并、长度限 255、空名返回 `'empty'`。
- `save(destination, overwrite=False)`：若目标是目录则拼上 `filename`；默认不覆盖（存在则 `IOError`）；否则按 `chunk_size`（默认 64KB）用 `_copy_file` 复制到目标（文件/目录/打开的文件对象）。

---

## 4. 服务器适配层

### 4.1 基类 `ServerAdapter`（@131575）
- 构造：记录 `host`（默认 127.0.0.1）、`port`（默认 8080）、`options`；`quiet` 类属性控制日志。
- `run(handler)` 为可继承入口；`_listen_url` 生成监听 URL（含 IPv6 与 `unix:` 处理）。

### 4.2 内置适配器清单（逐个；均继承 `ServerAdapter`，都在 13 万字符之后）
| 类名 | 位置 | 底层实现 / 备注 |
|---|---|---|
| `CGIServer` | @131700 | 用 `wsgiref.handlers.CGIHandler`，固定补 `PATH_INFO` 空值；`quiet=True` |
| `FlupFCGIServer` | @131820 | 用 `flup.server.fcgi.WSGIServer` |
| **`WSGIRefServer`** | @132861 | **自带参考实现**：用 `wsgiref.simple_server.make_server`；IPv6 地址时把 server 类 `address_family=AF_INET6`；update 实际端口（port=0 随机）；`serve_forever()` |
| `CherryPyServer` | @134300 | 用旧 `cherrypy.wsgiserver`（已弃用提示） |
| `CherootServer` | @134600 | 用 `cheroot.wsgi.Server`，支持 cert/key SSL |
| `WaitressServer` | @135000 | 用 `waitress.serve` |
| `PasteServer` | @135200 | `paste.httpserver` + `TransLogger` |
| `MeinheldServer` | @135500 | 用 `meinheld` |
| `FapwsServer` | @135700 | 用 `fapws._evwsgi`（已弃用）；含 `BOTTLE_CHILD` 提示 |
| `TornadoServer` | @136000 | `tornado.wsgi + httpserver + ioloop` |
| `AppEngineServer` | @136200 | Google App Engine（已弃用） |
| `TwistedServer` | @136500 | `twisted.web.wsgi` + 线程池 |
| `DieselServer` | @136900 | diesel（已弃用） |
| **`GeventServer`** | @139494 | 用 `gevent.pywsgi.WSGIServer`；需先 `gevent.monkey.patch_all()`（否则抛 RuntimeError）；`serve_forever()` |
| `GunicornServer` | @140000 | 用 `gunicorn.app.base.BaseApplication`，支持 `unix:` bind |
| `EventletServer` | @140500 | `eventlet.wsgi.server`，需 monkey_patch |
| `BjoernServer` | @141500 | C 写的 `bjoern` |
| `AsyncioServerAdapter` | @141800 | 抽象基类，提供 `get_event_loop` |
| `AiohttpServer` | @141900 | `aiohttp_wsgi.wsgi.serve` |
| `AiohttpUVLoopServer` | @142600 | 继承 AiohttpServer，用 uvloop |
| `AutoServer` | @142700 | `adapters=[WaitressServer, PasteServer, TwistedServer, CherryPyServer, CherootServer, WSGIRefServer]`，逐个 try 直到无 ImportError |

### 4.3 `run()` 如何选择与启动服务器（模块级函数 `run` @139000 附近，实际在 `server_names` 之后 "Application Control" 区）
- 签名：`run(app=None, server='wsgiref', host='127.0.0.1', port=8080, interval=1, reloader=False, quiet=False, plugins=None, debug=None, config=None, **kargs)`。
- **服务器解析链**（`server_names` dict @~138000 定义名称→类）：
  1. `server` 若是字符串并命中 `server_names` → 取对应类；仍是字符串（如模块路径）→ `load(server)` 导入；若是 `type` → `server(host, port, **kargs)` 实例化为适配器；最后 `isinstance(server, ServerAdapter)` 校验，否则抛 `ValueError("Unknown or unsupported server")`。
  2. 若无 `app` 参数，用 `default_app()`（即 `AppStack()` 栈顶）。
  3. 安装 `plugins`、应用 `config`。
- **启动**：
  - `reloader=True` 且非 `BOTTLE_CHILD` 子进程时，fork 一个子进程并从 lockfile 守护（`FileCheckerThread` 监控文件 mtime，变更则退出码 3 触发重启）。
  - `server.quiet` 未静默时打印启动横幅、监听地址。
  - 最终 `server.run(app)`——由所选适配器启动真实服务器，并把 `Bottle` 实例本身作为 WSGI handler 传入（适配器内部把这些 `environ/start_response` 交给 `Bottle.__call__/wsgi` 处理）。
- 模块末尾若以脚本运行（`__main__`）：`_main()` 解析 CLI（`--bind`、`--port`、`--server`、`--reload`、`--plugin`、`--debug`、`--conf` 配置文件、`--param`），构造 `ConfigDict`（支持 json/ini）后调用 `run(...)`。

### 4.4 默认请求/响应全局对象（模块末尾 @175000 附近）
```
request = LocalRequest()
response = LocalResponse()
apps = app = default_app = AppStack()   # 默认应用栈
TEMPLATES = {}, TEMPLATE_PATH = ['./','./views/'], DEBUG=False, NORUN=False
```

---

## 关键符号索引（字符偏移）
- `class Bottle` @7467；`Bottle.wsgi/@__call__` @41999/`__call__` @5750（class 内）
- `class Router` @7915；`Router.match` @15702；`Router._compile` ~@12000；`Router.build` @?（builder 区内）
- `class Route` @7810；`get_callback_args` @?；`_make_callback` @?
- `class BaseRequest` @44328；`class LocalRequest` @76054；`class BaseResponse` @64171；`class LocalResponse` @76504
- `class HTTPResponse` @77101；`class HTTPError` @77660；`class AppStack` @98295；`class ConfigDict` @89045
- `class FileUpload` @103482（>10 万字符）
- `class ServerAdapter` @131575；`class WSGIRefServer` @132861；`class GeventServer` @139494（均 >10 万字符）
- `server_names` @~138000；`def run(app,...)` @139000 附近（Application Control 区）
