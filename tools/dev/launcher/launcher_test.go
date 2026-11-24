package main

import (
	"archive/zip"
	"bytes"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// ---------- 假的操作系统 ----------

type fakeCon struct{ lines []string }

func (c *fakeCon) Say(s string)   { c.lines = append(c.lines, s) }
func (c *fakeCon) Print(s string) { c.lines = append(c.lines, s) }
func (c *fakeCon) Pause(s string) { c.lines = append(c.lines, "<等回车>") }
func (c *fakeCon) text() string   { return strings.Join(c.lines, "\n") }

type fake struct {
	files    map[string]bool
	env      map[string]string
	boxes    []string
	consoles int
	con      *fakeCon
	started  [][]string
	ran      [][]string
	removed  []string
	onRun    func(f *fake, cmd []string) int // 没设：一律 0
	onQuiet  func(cmd []string) int
	fetchErr error
	fetched  int
}

func newFake(files ...string) *fake {
	f := &fake{files: map[string]bool{}, env: map[string]string{}, con: &fakeCon{}}
	for _, x := range files {
		f.files[x] = true
	}
	return f
}

func (f *fake) ops() ops {
	return ops{
		isFile:  func(p string) bool { return f.files[p] },
		msg:     func(t string) { f.boxes = append(f.boxes, t) },
		console: func() console { f.consoles++; return f.con },
		start: func(exe string, args []string, dir string) error {
			f.started = append(f.started, append([]string{exe}, args...))
			return nil
		},
		run: func(con console, exe string, args []string, dir string) int {
			cmd := append([]string{exe}, args...)
			f.ran = append(f.ran, cmd)
			if f.onRun != nil {
				return f.onRun(f, cmd)
			}
			return 0
		},
		quiet: func(exe string, args []string) int {
			if f.onQuiet != nil {
				return f.onQuiet(append([]string{exe}, args...))
			}
			return 1
		},
		removeAll: func(p string) error { f.removed = append(f.removed, p); return nil },
		mkdirAll:  func(p string) error { return nil },
		fetchUV: func(con console, p paths) error {
			f.fetched++
			if f.fetchErr == nil {
				f.files[p.uv] = true
			}
			return f.fetchErr
		},
		setenv: func(k, v string) { f.env[k] = v },
	}
}

var (
	root = filepath.Join("D:", "游戏", "龙娘pcr")
	exe  = filepath.Join(root, "龙娘pcr.exe")
	lad  = filepath.Join("C:", "Users", "某人", "AppData", "Local")
	P    = mkPaths(root, lad)
)

// ---------- 路径、环境变量、启动方式 ----------

func TestPathsEnvAndMode(t *testing.T) {
	if P.menu != filepath.Join(root, "tools", "menu.py") || P.py != filepath.Join(lad, "longniang-pcr", "venv", "Scripts", "python.exe") ||
		P.pyw != filepath.Join(lad, "longniang-pcr", "venv", "Scripts", "pythonw.exe") || P.uv != filepath.Join(lad, "longniang-pcr", "bin", "uv.exe") {
		t.Fatalf("路径不对：%+v", P)
	}
	env := map[string]string{}
	for _, kv := range runtimeEnv(P, exe) {
		env[kv[0]] = kv[1]
	}
	want := map[string]string{ // 和原来 启动.bat 里设的一样，多一个 LNPCR_EXE
		"LNPCR_RUNTIME": P.rt, "LNPCR_UV": P.uv, "LNPCR_EXE": exe,
		"UV_CACHE_DIR": filepath.Join(P.rt, "cache", "uv"), "UV_PYTHON_INSTALL_DIR": filepath.Join(P.rt, "python"),
		"UV_PYTHON_PREFERENCE": "only-managed", "PIP_CACHE_DIR": filepath.Join(P.rt, "cache", "pip"),
		"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONPYCACHEPREFIX": filepath.Join(P.rt, "pycache"),
	}
	if !reflect.DeepEqual(env, want) {
		t.Fatalf("环境变量不对：%v", env)
	}
	for _, c := range []struct {
		args []string
		kind string
	}{{nil, "window"}, {[]string{"--setup"}, "setup"}, {[]string{"clear", "--tier", "2"}, "cli"}, {[]string{"console"}, "cli"}} {
		if k, rest := mode(c.args); k != c.kind || (k == "cli" && !reflect.DeepEqual(rest, c.args)) {
			t.Fatalf("mode(%v) = %s %v", c.args, k, rest)
		}
	}
	if !strings.HasPrefix(uvURL, "https://github.com/astral-sh/uv/releases/") {
		t.Fatal("uv 只从它自己的 GitHub 发布页下载")
	}
}

// ---------- 整个流程 ----------

func TestDoubleClickWithEverythingReady(t *testing.T) {
	f := newFake(P.menu, P.py, P.pyw)
	if code := flow(f.ops(), exe, lad, nil); code != 0 {
		t.Fatal(code)
	}
	if f.consoles != 0 || len(f.ran) != 0 || len(f.boxes) != 0 || f.fetched != 0 { // 平时：没有黑窗口，什么都不装
		t.Fatalf("不该开窗口 / 运行别的：%+v", f)
	}
	if !reflect.DeepEqual(f.started, [][]string{{P.pyw, P.menu, "window"}}) {
		t.Fatalf("%v", f.started)
	}
	if f.env["LNPCR_RUNTIME"] != P.rt || f.env["LNPCR_EXE"] != exe || f.env["PYTHONUTF8"] != "1" {
		t.Fatalf("%v", f.env)
	}
}

func TestNotInTheProjectFolder(t *testing.T) {
	f := newFake(P.py, P.pyw) // 没有 tools/menu.py：比如在压缩包里直接双击
	if code := flow(f.ops(), exe, lad, nil); code != 1 || len(f.boxes) != 1 || !strings.Contains(f.boxes[0], "解压") || len(f.started)+len(f.ran) != 0 {
		t.Fatalf("%d %v", code, f.boxes)
	}
	f = newFake(P.menu)
	if code := flow(f.ops(), exe, "", nil); code != 1 || len(f.boxes) != 1 || !strings.Contains(f.boxes[0], "LOCALAPPDATA") {
		t.Fatalf("%d %v", code, f.boxes)
	}
}

// 第一次运行：下载 uv → uv 建环境 → 装依赖 → 打开界面
func TestFirstRunWithUV(t *testing.T) {
	f := newFake(P.menu)
	f.onRun = func(f *fake, cmd []string) int {
		if cmd[0] == P.uv {
			f.files[P.py], f.files[P.pyw] = true, true
		}
		return 0
	}
	if code := flow(f.ops(), exe, lad, nil); code != 0 {
		t.Fatal(code, f.con.text())
	}
	want := [][]string{
		{P.uv, "venv", "--python", "3.12", "--seed", "--clear", P.venv},
		{P.py, P.menu, "prepare"},
	}
	if f.consoles != 1 || f.fetched != 1 || !reflect.DeepEqual(f.ran, want) || !reflect.DeepEqual(f.started, [][]string{{P.pyw, P.menu, "window"}}) {
		t.Fatalf("%v %v", f.ran, f.started)
	}
	txt := f.con.text()
	for _, s := range []string{"第一次运行", P.rt, "[1/3] 下载 uv", "[2/3] 准备 Python 3.12"} {
		if !strings.Contains(txt, s) {
			t.Fatalf("没说 %q：\n%s", s, txt)
		}
	}
	if strings.Contains(txt, "<等回车>") || len(f.boxes) != 0 {
		t.Fatal("顺利的时候不用等回车、不弹框")
	}
	// uv 已经下过：不再下
	f2 := newFake(P.menu, P.uv)
	f2.onRun = f.onRun
	if flow(f2.ops(), exe, lad, nil) != 0 || f2.fetched != 0 || strings.Contains(f2.con.text(), "[1/3]") {
		t.Fatal("uv 在的话不重新下载")
	}
}

// uv 下不下来：用电脑上已经装好的 Python（先 py -3，再 python）
func TestFirstRunFallsBackToSystemPython(t *testing.T) {
	f := newFake(P.menu)
	f.fetchErr = errors.New("连不上")
	var asked [][]string
	f.onQuiet = func(cmd []string) int {
		asked = append(asked, cmd)
		if cmd[0] == "python" {
			return 0
		}
		return 1 // 没有 py 启动器
	}
	f.onRun = func(f *fake, cmd []string) int {
		if cmd[0] == "python" && cmd[1] == "-m" {
			f.files[P.py], f.files[P.pyw] = true, true
		}
		return 0
	}
	if code := flow(f.ops(), exe, lad, nil); code != 0 {
		t.Fatal(code, f.con.text())
	}
	if !reflect.DeepEqual(asked, [][]string{{"py", "-3", "-c", pyCheck}, {"python", "-c", pyCheck}}) {
		t.Fatalf("%v", asked)
	}
	if !reflect.DeepEqual(f.ran, [][]string{{"python", "-m", "venv", P.venv}, {P.py, P.menu, "prepare"}}) || len(f.started) != 1 {
		t.Fatalf("%v", f.ran)
	}
	if !strings.Contains(f.con.text(), "没下载下来：连不上") || !strings.Contains(f.con.text(), "改用电脑上已经装好的 Python") {
		t.Fatal(f.con.text())
	}
}

func TestFirstRunFails(t *testing.T) {
	f := newFake(P.menu)
	f.fetchErr = errors.New("连不上")
	if code := flow(f.ops(), exe, lad, nil); code != 1 {
		t.Fatal(code)
	}
	txt := f.con.text()
	if len(f.started) != 0 || len(f.ran) != 0 || !strings.Contains(txt, "没能准备好 Python 运行环境") || !strings.Contains(txt, "再双击一次“龙娘pcr.exe”") ||
		!strings.HasSuffix(txt, "<等回车>") || strings.Contains(txt, "启动.bat") {
		t.Fatalf("%v\n%s", f.ran, txt)
	}
	// uv 下到了，但建环境失败（比如连不上下载 Python 的地方），电脑上也没有 Python
	f = newFake(P.menu, P.uv)
	f.onRun = func(f *fake, cmd []string) int { return 2 }
	if code := flow(f.ops(), exe, lad, nil); code != 1 || len(f.started) != 0 || !reflect.DeepEqual(f.removed, []string{P.venv}) {
		t.Fatalf("%d %v %v", code, f.started, f.removed)
	}
}

// 依赖没装上（tools/menu.py prepare 返回非 0）：不打开界面
func TestPrepareFails(t *testing.T) {
	f := newFake(P.menu, P.py, P.pyw)
	f.onRun = func(f *fake, cmd []string) int { return 1 }
	if code := flow(f.ops(), exe, lad, []string{"--setup"}); code != 1 || len(f.started) != 0 || f.consoles != 1 {
		t.Fatalf("%d %v", code, f.started)
	}
}

// 界面发现依赖不全，带着 --setup 叫回来：开窗口装依赖，再打开界面
func TestSetupMode(t *testing.T) {
	f := newFake(P.menu, P.py, P.pyw)
	if code := flow(f.ops(), exe, lad, []string{"--setup"}); code != 0 {
		t.Fatal(code)
	}
	if f.consoles != 1 || !reflect.DeepEqual(f.ran, [][]string{{P.py, P.menu, "prepare"}}) || !reflect.DeepEqual(f.started, [][]string{{P.pyw, P.menu, "window"}}) {
		t.Fatalf("%v %v", f.ran, f.started)
	}
	// 没有 pythonw：带着窗口开界面
	f = newFake(P.menu, P.py)
	if code := flow(f.ops(), exe, lad, nil); code != 0 || len(f.started) != 0 ||
		!reflect.DeepEqual(f.ran, [][]string{{P.py, P.menu, "prepare"}, {P.py, P.menu, "gui"}}) {
		t.Fatalf("%v", f.ran)
	}
}

// 原来的「启动.bat clear」之类：参数原样交给 tools/menu.py
func TestCommandLine(t *testing.T) {
	f := newFake(P.menu, P.py, P.pyw)
	if code := flow(f.ops(), exe, lad, []string{"clear", "--tier", "2"}); code != 0 {
		t.Fatal(code)
	}
	if f.consoles != 1 || len(f.started) != 0 || !reflect.DeepEqual(f.ran, [][]string{{P.py, P.menu, "clear", "--tier", "2"}}) || strings.Contains(f.con.text(), "<等回车>") {
		t.Fatalf("%v", f.ran)
	}
	f = newFake(P.menu, P.py, P.pyw)
	f.onRun = func(f *fake, cmd []string) int { return 3 }
	if code := flow(f.ops(), exe, lad, []string{"export"}); code != 3 || !strings.HasSuffix(f.con.text(), "<等回车>") { // 出了大错：留着窗口让人看
		t.Fatalf("%d %s", code, f.con.text())
	}
}

// ---------- 代理、下载、解压 ----------

func TestParseProxy(t *testing.T) {
	for in, want := range map[string]string{
		"":                                  "",
		"127.0.0.1:7890":                    "http://127.0.0.1:7890",
		" proxy.local:8080 ":                "http://proxy.local:8080",
		"http://10.0.0.1:3128":              "http://10.0.0.1:3128",
		"http=1.1.1.1:80;https=2.2.2.2:443": "http://2.2.2.2:443",
		"http=1.1.1.1:80":                   "http://1.1.1.1:80",
		"socks=127.0.0.1:1080":              "socks5://127.0.0.1:1080",
		"socks=socks5://127.0.0.1:1080":     "socks5://127.0.0.1:1080",
		"ftp=1.1.1.1:21":                    "",
		"gopher://x:1":                      "",
		"::::":                              "",
	} {
		got := ""
		if u := parseProxy(in); u != nil {
			got = u.String()
		}
		if got != want {
			t.Errorf("parseProxy(%q) = %q，应该是 %q", in, got, want)
		}
	}
}

func makeZip(t *testing.T, files map[string]string) []byte {
	t.Helper()
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	for name, body := range files {
		w, err := zw.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		w.Write([]byte(body))
	}
	zw.Close()
	return buf.Bytes()
}

func TestPickAndUnzip(t *testing.T) {
	if pickUV([]string{"uvx.exe", "uv.exe", "uvw.exe"}) != 1 || pickUV([]string{"uv-x86_64-pc-windows-msvc/", "uv-x86_64-pc-windows-msvc/uvx.exe", `uv-x86_64-pc-windows-msvc\UV.EXE`}) != 2 ||
		pickUV([]string{"uvx.exe", "notuv.exe", "uv.exe/"}) != -1 {
		t.Fatal("pickUV")
	}
	dir := t.TempDir()
	zp := filepath.Join(dir, "uv.zip")
	os.WriteFile(zp, makeZip(t, map[string]string{"uv-x/uvx.exe": "别的", "uv-x/uv.exe": "这是 uv"}), 0o644)
	dst := filepath.Join(dir, "uv.exe")
	if err := unzipUV(zp, dst); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(dst); string(b) != "这是 uv" {
		t.Fatalf("%q", b)
	}
	os.WriteFile(zp, makeZip(t, map[string]string{"readme.txt": "x"}), 0o644)
	if err := unzipUV(zp, dst); err == nil || !strings.Contains(err.Error(), "没有 uv.exe") {
		t.Fatal(err)
	}
	os.WriteFile(zp, []byte("不是压缩包"), 0o644)
	if unzipUV(zp, dst) == nil {
		t.Fatal("坏的压缩包应该报错")
	}
}

func TestFetchUVOverHTTP(t *testing.T) {
	body := makeZip(t, map[string]string{"uv.exe": strings.Repeat("uv", 50000), "uvx.exe": "x"})
	var hits int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/latest/uv.zip": // 和 GitHub 一样：先跳转一次
			http.Redirect(w, r, "/real/uv.zip", http.StatusFound)
		case "/real/uv.zip":
			if atomic.AddInt32(&hits, 1) == 1 { // 第一次故意出错：要会重试
				http.Error(w, "忙", http.StatusBadGateway)
				return
			}
			w.Header().Set("Content-Length", fmt.Sprint(len(body)))
			w.Write(body)
		case "/short.zip": // 说有这么多，其实只给一半
			w.Header().Set("Content-Length", fmt.Sprint(len(body)))
			w.Write(body[:len(body)/2])
		case "/stall.zip": // 发一点就卡住
			w.Header().Set("Content-Length", fmt.Sprint(len(body)))
			w.Write(body[:100])
			w.(http.Flusher).Flush()
			select {
			case <-r.Context().Done():
			case <-time.After(5 * time.Second):
			}
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()
	dir := t.TempDir()
	p := paths{uv: filepath.Join(dir, "bin", "uv.exe")}
	os.MkdirAll(filepath.Dir(p.uv), 0o755)
	con := &fakeCon{}
	client := newClient("")
	if err := download(con, client, srv.URL+"/latest/uv.zip", p.uv+".zip", 3, 5*time.Second, time.Millisecond); err != nil {
		t.Fatal(err, con.text())
	}
	if b, _ := os.ReadFile(p.uv + ".zip"); !bytes.Equal(b, body) {
		t.Fatal("下载下来的不一样")
	}
	if !strings.Contains(con.text(), "第 1 次没成") || !strings.Contains(con.text(), "已下载 100%") {
		t.Fatal(con.text())
	}
	os.Remove(p.uv + ".zip")
	if err := fetchUV(con, client, srv.URL+"/latest/uv.zip", p); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(p.uv); string(b) != strings.Repeat("uv", 50000) {
		t.Fatal("uv.exe 不对")
	}
	left, _ := filepath.Glob(filepath.Join(dir, "bin", "*"))
	if len(left) != 1 { // 压缩包、.part 都不留
		t.Fatalf("留下了别的东西：%v", left)
	}
	for _, bad := range []string{"/nothing.zip", "/short.zip"} {
		if err := download(con, client, srv.URL+bad, filepath.Join(dir, "x.zip"), 2, 5*time.Second, time.Millisecond); err == nil {
			t.Fatalf("%s 应该失败", bad)
		}
	}
	t0 := time.Now()
	if err := downloadOnce(client, srv.URL+"/stall.zip", filepath.Join(dir, "y.zip"), 300*time.Millisecond, nil); err == nil || time.Since(t0) > 3*time.Second {
		t.Fatalf("卡住的下载应该很快放弃：%v %v", err, time.Since(t0))
	}
	if m, _ := filepath.Glob(filepath.Join(dir, "*.zip*")); len(m) != 0 {
		t.Fatalf("失败的下载不该留下文件：%v", m)
	}
}
