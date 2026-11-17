# docs · GitHub Pages 部署目录

这个目录只做一件事：让「HTML 普通版」有一个可以直接分享的网址。

## 在线地址

**https://sixwateer.github.io/clear-water-print/**

手机、平板、任何电脑的浏览器都能直接打开，无需安装、无需联网处理——

> 图片全部在访问者自己的浏览器里处理，不上传服务器。页面本身是纯静态文件，
> 断网后（除首次加载）也能用。

## 这里的文件是怎么来的

`index.html` 是 `02_HTML版/净像去水印_普通版_双击即用.html` 的副本。
GitHub Pages 只把站点根目录的 `index.html` 当首页，而交付文件名是中文长名，
所以需要这个副本。

**改了 HTML 之后，务必先同步再提交：**

```bash
python "02_HTML版/发布到Pages.py"
```

不跑这一步，线上还是旧版本。脚本会打印源文件与副本的 sha256 前 8 位，便于核对。

## Pages 设置

仓库 Settings → Pages：

- Source：**Deploy from a branch**
- Branch：**main**，目录 **/docs**

如果换成 GitHub Actions 部署，需要额外维护 workflow 文件，且推送方的 token
需要 `workflow` 权限——当前用分支部署，少一层依赖。

## 说明

`docs/` 目录里只放部署所需文件，不要把示例图、测试产物塞进来：
Pages 站点是公开的，且会拖慢首次加载。
