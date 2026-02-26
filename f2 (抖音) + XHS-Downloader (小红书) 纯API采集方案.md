
# f2 (抖音) + XHS-Downloader (小红书) 纯API采集方案

你好，在对 `f2` 和 `XHS-Downloader` 两个项目进行深度源码分析后，我为你整理了这份最终的技术选型方案。此方案完全遵循你“不使用浏览器自动化”的核心要求，全部采用纯API请求的方式实现，是性能最高、最适合后端集成的选择。

## 1. 核心技术栈与实现原理

此方案的基石是两个项目对各自平台签名算法的纯Python实现，从而摆脱了对浏览器环境的依赖。

- **抖音 (`f2`)**: 项目内置了 `A-Bogus` 签名算法的完整Python实现 (`f2/utils/abogus.py`)。它通过模拟浏览器的指纹信息，构造请求参数，并执行一系列复杂的加密和位运算来生成合法的 `a_bogus` 参数，附加在API请求上。

- **小红书 (`XHS-Downloader`)**: 此项目巧妙地将签名逻辑外包给了 `xhshow` 这个独立的纯Python库。`xhshow` 实现了小红书 `x-s` 和 `x-t` 签名的生成算法，同样无需任何浏览器环境。

## 2. 抖音采集方案 (基于 `f2`)

`f2` 的结构清晰，模块化程度高。按作者采集的核心逻辑分散在 `handler`, `crawler`, 和 `utils` 模块中。

### 2.1. 实现流程

1.  **获取作者ID**: 使用 `f2.apps.douyin.utils.SecUserIdFetcher` 类，通过一个HTTP请求自动从作者主页的URL（无论是长链接还是短链接）中解析出 `sec_user_id`。

2.  **初始化采集器**: 实例化 `f2.apps.douyin.handler.DouyinHandler`。这个类是所有操作的总入口，它会管理配置（如Cookie）和初始化下载器等组件。

3.  **分页获取作品**: 调用 `DouyinHandler` 实例的 `fetch_user_post_videos` 方法。这是一个异步生成器，它内部封装了分页逻辑：
    a.  **构造请求**: 在循环中，它会创建一个 `f2.apps.douyin.model.UserPost` 的Pydantic模型实例，包含 `sec_user_id`, `max_cursor` (用于分页), `count` 等参数。
    b.  **调用Crawler**: `DouyinCrawler` 的 `fetch_user_post` 方法被调用。此方法的核心是 `ABogusManager.model_2_endpoint`，它负责将请求参数和 `a_bogus` 签名拼接成最终的API请求URL。
    c.  **发送请求**: 使用 `httpx` 发送GET请求到抖音的 `/aweme/v1/web/aweme/post/` 接口。
    d.  **解析与返回**: 响应的JSON数据被 `f2.apps.douyin.filter.UserPostFilter` 类包装，该类提供了方便的属性（如 `.aweme_id`, `.desc`）来访问数据。
    e.  **循环**: `fetch_user_post_videos` 方法会从响应中提取新的 `max_cursor`，并在下一次循环中用它来获取下一页数据，直到 `has_more` 字段为 `False`。

### 2.2. 关键模块

- **`handler.py`**: 顶层业务逻辑封装，如 `handle_user_post` 和 `fetch_user_post_videos`。
- **`crawler.py`**: 负责构造最终请求URL（含签名）并使用 `httpx` 发起HTTP请求。
- **`utils.py`**: 包含 `SecUserIdFetcher`（解析URL）和 `ABogusManager`（调用签名算法）等核心工具类。
- **`abogus.py`**: `A-Bogus` 签名算法的纯Python实现，是整个方案的基石。
- **`model.py`**: 定义了所有API请求的Pydantic模型，如 `UserPost`。
- **`filter.py`**: 定义了所有API响应的解析类，如 `UserPostFilter`，极大地方便了数据提取。


## 3. 小红书采集方案 (基于 `XHS-Downloader`)

`XHS-Downloader` 的设计同样精巧，它将核心的签名功能委托给 `xhshow` 库，自身则专注于业务逻辑、数据处理和用户交互。

### 3.1. 实现流程

1.  **获取作者ID**: 与 `f2` 类似，需要先从作者主页URL中解析出 `user_id`。这通常是通过一个初始的HTTP请求到主页HTML，然后从HTML内容中提取。

2.  **初始化采集器**: 实例化 `XHS` 类 (`source/application/app.py`)。这个类是总控制器，初始化了 `Manager`（管理配置、Cookie、HTTP客户端等）和各种子模块。

3.  **分页获取作品**: `XHS-Downloader` 的作者采集逻辑并非一个独立的函数，而是分散在 `extract_links` 和 `__deal_extract` 等方法中，但其核心是调用 `user_posted` 模块。我们可以将其逻辑提炼如下：
    a.  **构造请求**: 创建一个 `UserPosted` 类的实例 (`source/application/user_posted.py`)。这个类接收 `user_id`, `cursor` (用于分页) 等参数。
    b.  **调用签名**: 在 `UserPosted.get_data` 方法内部，它会调用 `self.encipher.sign_headers_get`。这个 `encipher` 就是 `xhshow.Xhshow` 的实例。`sign_headers_get` 方法负责生成包含 `x-s`, `x-t` 等签名的完整请求头。
    c.  **发送请求**: 使用 `httpx` 向小红书的 `/api/sns/web/v1/user_posted` 接口发送带有签名头信息的GET请求。
    d.  **解析与返回**: 响应的JSON数据被包装在 `Namespace` 对象中，通过 `explore.py` 中的 `Explore` 类进行结构化提取，得到标题、ID、点赞数等信息。
    e.  **循环**: 从响应中提取 `cursor` 和 `has_more` 字段，循环调用上述过程，直到 `has_more` 为 `False`，从而获取所有作品。

### 3.2. 关键模块

- **`app.py`**: 主应用类 `XHS`，负责初始化和调度所有功能。
- **`user_posted.py`**: 封装了针对 `/api/sns/web/v1/user_posted` 接口的请求逻辑，是按作者采集的核心。
- **`manager.py`**: `Manager` 类，管理全局配置，如Cookie、代理、HTTP客户端 (`httpx.AsyncClient`) 等。
- **`explore.py`**: `Explore` 类，负责将从API获取的原始JSON数据格式化为易于使用的字典结构。
- **`xhshow` (外部库)**: 这是整个方案能够脱离浏览器的关键。它提供了 `sign_headers_get` 等方法，纯Python实现了 `x-s` 签名的生成。


## 4. 核心代码实现

为了让你能快速上手，我已将上述分析提炼为两个可直接运行的 Python 脚本，分别对应抖音和小红书的作者作品采集。

**请注意**: 这两个脚本都需要你填入自己的有效 Cookie 才能成功请求数据。

### 4.1. 抖音采集核心代码 (`f2_douyin_author_scraper.py`)

此脚本直接利用 `f2` 库的 `DouyinHandler` 来实现功能。它封装了所有复杂的签名和分页逻辑，调用非常简洁。

- **依赖**: `f2` (`pip install f2`)
- **使用**: 将你的抖音网页版 Cookie 填入 `YOUR_COOKIE_HERE`，修改 `author_url` 为目标作者主页，然后直接运行脚本。

*完整代码见附件 `f2_douyin_author_scraper.py`*

### 4.2. 小红书采集核心代码 (`xhsdownloader_author_scraper.py`)

此脚本的核心是调用 `xhshow` 库来生成签名。为了保持代码的轻量和独立，我没有直接依赖 `XHS-Downloader` 的整个项目，而是根据其源码分析，重新实现了核心的请求和分页逻辑。

- **依赖**: `xhshow`, `httpx` (`pip install xhshow httpx`)
- **使用**: 将你的小红书网页版 Cookie 填入 `YOUR_COOKIE_HERE`，修改 `author_url` 为目标作者主页，然后直接运行脚本。

*完整代码见附件 `xhsdownloader_author_scraper.py`*

## 5. 结论

`f2` + `XHS-Downloader` (及其核心依赖 `xhshow`) 的组合，为你提供了一个高性能、高稳定性的纯 API 采集方案。它完全避免了浏览器自动化的性能瓶颈和不稳定性，非常适合在你的后端服务中进行集成。这份方案和配套的核心代码，将能帮助你高效、可靠地完成抖音和小红书的按作者采集功能开发。
