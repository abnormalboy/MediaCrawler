# -*- coding: utf-8 -*-
"""小红书 App ADB 自动化用到的包名、deeplink 与文案常量。"""

# 小红书官方包名
XHS_PACKAGE = "com.xingin.xhs"

# 首页 Activity
XHS_HOME_ACTIVITY = "com.xingin.xhs/.index.v2.IndexActivityV2"

# 搜索结果页。keyword 需做 URL 编码
# 例：xhsdiscover://search/result?keyword=%E5%90%A7%E5%94%A7
XHS_SEARCH_RESULT_URI = "xhsdiscover://search/result?keyword={keyword}"

# 登录/掉线相关文案（resource-id 被混淆，只能靠文本判断）
LOGIN_HINT_TEXTS = (
    "账号下线提示",
    "账号已退出登录",
    "登录查看更多精彩内容",
    "登录后发现精彩内容",
    "去登录",
    "重新登录",
    "微信登录",
    "手机号登录",
)

# 打开笔记详情时若未登录，会弹出半屏欢迎页
LOGIN_ACTIVITY_MARKERS = (
    "HalfWelcomeActivity",
    "login.halfwelcome",
    "NotificationAuthorization",
)

# 搜索页顶栏关键词输入框附近的「搜索」按钮文案
SEARCH_BUTTON_TEXT = "搜索"

# 详情页右侧「分享N」按钮的 content-desc 前缀
SHARE_DESC_PREFIX = "分享"

# 分享面板里复制笔记短链的按钮
COPY_LINK_TEXT = "复制链接"

# 分享文案里的短链，例如 https://xhslink.cn/o/xxxxx
XHS_SHORT_LINK_RE = r"https://xhslink\.[a-z]+/\S+"

# 详情页底部评论框占位，粘贴短链用，避免动到顶栏搜索
COMMENT_INPUT_HINTS = (
    "让大家听到你的声音",
    "有话要说，快来评论",
    "留下你的想法吧",
    "说点什么...",
    "说点什么",
)

# 列表页底栏提示，解析卡片时忽略
NOISE_TEXTS = {
    "搜索",
    "全部",
    "问点点",
    "返回",
    "全部删除",
    "登录查看更多精彩内容",
    "去登录",
    "搜索后支持下拉刷新",
    "帮助",
    "首页",
    "市集",
    "发布",
    "消息",
    "我",
    "关注",
    "发现",
    "同城",
}
