// 龙娘pcr.exe 的源代码（正式版 V1.0，2026-11-25）。
//
// 以前有两个入口：启动.bat（第一次准备 Python 运行环境、装依赖、做 exe）和每台电脑现做的 龙娘pcr.exe。
// 现在 启动.bat 没有了，它干的事全在这个 exe 里：
//
//	双击                →  运行环境在：直接用 pythonw 打开界面（没有黑窗口）
//	                       运行环境不在：开一个看得到进度的窗口，准备好了再打开界面
//	龙娘pcr.exe clear | farm | scan | setup | export | console   →  在窗口里直接跑某一项（原来的 启动.bat xxx）
//	龙娘pcr.exe --setup →  内部用：界面发现依赖不全时，叫它来装
//
// 这个程序只做这几件事：看几个文件在不在、设几个环境变量、从 github.com/astral-sh/uv 下载 uv、
// 运行 uv / python。不读也不改游戏、模拟器、别的任何东西。只用 Go 的标准库。
package main

import (
	"path/filepath"
	"strings"
)

const (
	appName = "龙娘pcr"
	// 和原来 启动.bat 里的那一行是同一个地址
	uvURL   = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
	pyCheck = "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)"
)

type paths struct {
	root, menu, rt, venv, py, pyw, uv string
}

// Python 运行环境、缓存、临时文件都放在纯英文目录 %LOCALAPPDATA%\longniang-pcr；项目文件留在 exe 所在的文件夹。
func mkPaths(root, localAppData string) paths {
	rt := filepath.Join(localAppData, "longniang-pcr")
	venv := filepath.Join(rt, "venv")
	return paths{
		root: root,
		menu: filepath.Join(root, "tools", "menu.py"),
		rt:   rt,
		venv: venv,
		py:   filepath.Join(venv, "Scripts", "python.exe"),
		pyw:  filepath.Join(venv, "Scripts", "pythonw.exe"),
		uv:   filepath.Join(rt, "bin", "uv.exe"),
	}
}

// 给 python / uv 用的环境变量（和原来 启动.bat 里设的一模一样），外加 LNPCR_EXE：这个 exe 自己在哪。
func runtimeEnv(p paths, exe string) [][2]string {
	return [][2]string{
		{"LNPCR_RUNTIME", p.rt},
		{"LNPCR_UV", p.uv},
		{"LNPCR_EXE", exe},
		{"UV_CACHE_DIR", filepath.Join(p.rt, "cache", "uv")},
		{"UV_PYTHON_INSTALL_DIR", filepath.Join(p.rt, "python")},
		{"UV_PYTHON_PREFERENCE", "only-managed"},
		{"PIP_CACHE_DIR", filepath.Join(p.rt, "cache", "pip")},
		{"PYTHONUTF8", "1"},
		{"PYTHONIOENCODING", "utf-8"},
		{"PYTHONPYCACHEPREFIX", filepath.Join(p.rt, "pycache")},
	}
}

// 怎么启动的：window（双击，没带参数）、setup（--setup）、cli（带了别的参数，原样交给 tools/menu.py）。
func mode(args []string) (string, []string) {
	if len(args) == 0 {
		return "window", nil
	}
	if args[0] == "--setup" {
		return "setup", nil
	}
	return "cli", args
}

// 看得到字的窗口。
type console interface {
	Say(line string)     // 写一行
	Print(text string)   // 不换行（下载进度用）
	Pause(prompt string) // 等一下回车
}

// 和操作系统打交道的几件事。真的那一套在 host_*.go；自测的时候换成假的。
type ops struct {
	isFile    func(path string) bool
	msg       func(text string)                                            // 弹框
	console   func() console                                               // 开窗口
	start     func(exe string, args []string, dir string) error            // 启动以后不管（界面）
	run       func(con console, exe string, args []string, dir string) int // 在窗口里运行，等它结束，返回退出码（没能运行：-1）
	quiet     func(exe string, args []string) int                          // 不出声地运行（探一探电脑上的 Python）
	removeAll func(path string) error
	mkdirAll  func(path string) error
	fetchUV   func(con console, p paths) error
	setenv    func(k, v string)
}

func flow(o ops, exe, localAppData string, args []string) int {
	if localAppData == "" {
		o.msg("系统没有给出 LOCALAPPDATA 这个位置，没法准备运行环境。")
		return 1
	}
	p := mkPaths(filepath.Dir(exe), localAppData)
	if !o.isFile(p.menu) {
		o.msg("这个 exe 要放在“龙娘pcr”文件夹里（和 tools、longniang_pcr 这些文件夹在一起）才能用。\n\n" +
			"如果你是在压缩包里直接双击的：先把整个压缩包解压出来，再双击解压出来的 龙娘pcr.exe。")
		return 1
	}
	for _, kv := range runtimeEnv(p, exe) {
		o.setenv(kv[0], kv[1])
	}
	kind, rest := mode(args)
	window := []string{p.menu, "window"}

	// 平时走这里：运行环境在，直接打开界面，没有黑窗口。依赖全不全由界面自己看，不全它会带着 --setup 再叫这个 exe。
	if kind == "window" && o.isFile(p.py) && o.isFile(p.pyw) {
		if err := o.start(p.pyw, window, p.root); err != nil {
			o.msg("没能打开界面：" + err.Error())
			return 1
		}
		return 0
	}

	con := o.console()
	if !o.isFile(p.py) && !bootstrap(o, con, p) {
		con.Say("")
		con.Say(" 没能准备好 Python 运行环境，多半是连不上 GitHub。")
		con.Say(" 两个办法，任选一个：")
		con.Say("   1. 检查网络（需要的话开着代理），然后再双击一次“龙娘pcr.exe”")
		con.Say("   2. 自己装一个 Python 3.12（python.org 下载，安装时勾选 Add python.exe to PATH），")
		con.Say("      然后再双击一次“龙娘pcr.exe”")
		con.Say("")
		con.Pause(" 按回车关闭这个窗口……")
		return 1
	}

	if kind == "cli" {
		code := o.run(con, p.py, append([]string{p.menu}, rest...), p.root)
		if code >= 2 || code < 0 {
			con.Pause(" 按回车关闭这个窗口……")
		}
		return code
	}

	// 检查 / 安装依赖（第一次要装东西，得看得到进度），然后用 pythonw 打开界面，这个窗口自己关掉。
	if code := o.run(con, p.py, []string{p.menu, "prepare"}, p.root); code != 0 {
		if code < 0 {
			con.Pause(" 按回车关闭这个窗口……")
		}
		return 1 // 依赖没装上：tools/menu.py 自己已经说了原因、等过回车
	}
	if o.isFile(p.pyw) {
		if err := o.start(p.pyw, window, p.root); err != nil {
			con.Say(" 没能打开界面：" + err.Error())
			con.Pause(" 按回车关闭这个窗口……")
			return 1
		}
		return 0
	}
	code := o.run(con, p.py, []string{p.menu, "gui"}, p.root) // 没有 pythonw：带着这个窗口开界面
	if code >= 2 || code < 0 {
		con.Pause(" 按回车关闭这个窗口……")
	}
	return code
}

// 第一次运行：准备 Python。先走 uv（自己下载一个 Python 3.12，不动电脑上别的 Python）；
// 走不通就用电脑上已经装好的 Python（3.10 ~ 3.13）建环境。返回行不行。
func bootstrap(o ops, con console, p paths) bool {
	con.Say("")
	con.Say(" 第一次运行，先准备 Python 运行环境。")
	con.Say(" 装在 " + p.rt)
	con.Say(" 需要联网，大约占 500 MB，要等几分钟。")
	con.Say("")
	if err := o.mkdirAll(filepath.Dir(p.uv)); err != nil {
		con.Say("   建不了文件夹：" + err.Error())
	}
	if !o.isFile(p.uv) {
		con.Say(" [1/3] 下载 uv（Python 环境管理工具，来自 github.com/astral-sh/uv）")
		if err := o.fetchUV(con, p); err != nil {
			con.Say("   没下载下来：" + err.Error())
		}
	}
	if o.isFile(p.uv) {
		con.Say(" [2/3] 准备 Python 3.12")
		_ = o.removeAll(p.venv)
		if o.run(con, p.uv, []string{"venv", "--python", "3.12", "--seed", "--clear", p.venv}, p.root) == 0 && o.isFile(p.py) {
			return true
		}
	}
	con.Say("")
	con.Say(" uv 这条路没走通，改用电脑上已经装好的 Python")
	for _, cand := range [][]string{{"py", "-3"}, {"python"}} {
		if o.quiet(cand[0], append(append([]string{}, cand[1:]...), "-c", pyCheck)) != 0 {
			continue
		}
		_ = o.removeAll(p.venv)
		o.run(con, cand[0], append(append([]string{}, cand[1:]...), "-m", "venv", p.venv), p.root)
		if o.isFile(p.py) {
			return true
		}
	}
	return false
}

// 压缩包里哪一个是 uv.exe（有的版本在最外层，有的在一个文件夹里）。没有返回 -1。
func pickUV(names []string) int {
	for i, n := range names {
		n = strings.ReplaceAll(n, "\\", "/")
		if strings.HasSuffix(n, "/") {
			continue
		}
		if j := strings.LastIndex(n, "/"); j >= 0 {
			n = n[j+1:]
		}
		if strings.EqualFold(n, "uv.exe") {
			return i
		}
	}
	return -1
}
