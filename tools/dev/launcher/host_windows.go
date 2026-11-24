//go:build windows

package main

import (
	"bytes"
	"os"
	"os/exec"
	"syscall"
	"unsafe"
)

// 只用 kernel32 / user32 / advapi32 这三个系统自带的库（都是 Windows 的“已知 DLL”，只会从系统目录加载）。
var (
	kernel32            = syscall.NewLazyDLL("kernel32.dll")
	user32              = syscall.NewLazyDLL("user32.dll")
	pAllocConsole       = kernel32.NewProc("AllocConsole")
	pSetConsoleTitleW   = kernel32.NewProc("SetConsoleTitleW")
	pSetConsoleOutputCP = kernel32.NewProc("SetConsoleOutputCP")
	pSetConsoleCP       = kernel32.NewProc("SetConsoleCP")
	pMessageBoxW        = user32.NewProc("MessageBoxW")
)

const (
	mbIconWarning         = 0x30
	detachedProcess       = 0x00000008
	createNewProcessGroup = 0x00000200
)

func msgBox(text string) {
	t, err1 := syscall.UTF16PtrFromString(text)
	c, err2 := syscall.UTF16PtrFromString(appName)
	if err1 != nil || err2 != nil {
		return
	}
	pMessageBoxW.Call(0, uintptr(unsafe.Pointer(t)), uintptr(unsafe.Pointer(c)), mbIconWarning)
}

// 这个程序本身没有黑窗口（双击打开界面时什么都不闪）。要显示进度的时候现开一个。
type winConsole struct {
	in, out *os.File
}

func openConsole() console {
	pAllocConsole.Call() // 已经有窗口的话这一步会失败，没关系，下面照样去开 CONOUT$
	pSetConsoleOutputCP.Call(65001)
	pSetConsoleCP.Call(65001)
	if t, err := syscall.UTF16PtrFromString(appName); err == nil {
		pSetConsoleTitleW.Call(uintptr(unsafe.Pointer(t)))
	}
	c := &winConsole{}
	if f, err := os.OpenFile("CONOUT$", os.O_RDWR, 0); err == nil {
		c.out = f
	}
	if f, err := os.OpenFile("CONIN$", os.O_RDWR, 0); err == nil {
		c.in = f
	}
	return c
}

func (c *winConsole) Print(text string) {
	if c.out != nil {
		c.out.WriteString(text)
	}
}

func (c *winConsole) Say(line string) { c.Print(line + "\r\n") }

func (c *winConsole) Pause(prompt string) {
	if c.out == nil || c.in == nil { // 窗口没开出来：弹个框，免得什么都看不到就没了
		msgBox("没能准备好运行环境，而且显示进度的窗口也没开出来。检查网络以后再双击一次“龙娘pcr.exe”。")
		return
	}
	c.Print(prompt)
	buf := make([]byte, 256)
	for {
		n, err := c.in.Read(buf)
		if err != nil || n == 0 || bytes.IndexByte(buf[:n], '\n') >= 0 {
			return
		}
	}
}

// 让子程序用这个窗口输入输出。
func attach(cmd *exec.Cmd, con console) {
	c, ok := con.(*winConsole)
	if !ok || c == nil {
		return
	}
	if c.in != nil {
		cmd.Stdin = c.in
	}
	if c.out != nil {
		cmd.Stdout = c.out
		cmd.Stderr = c.out
	}
}

// 启动界面（pythonw），然后不管它：这个 exe 退出以后界面照常开着。
func startDetached(exe string, args []string, dir string) error {
	cmd := exec.Command(exe, args...)
	cmd.Dir = dir
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: detachedProcess | createNewProcessGroup}
	if err := cmd.Start(); err != nil {
		return err
	}
	return cmd.Process.Release()
}

// Windows 设置里的「代理服务器」（只读注册表里那两项：开没开、地址是什么）。没开、读不到：返回空。
func systemProxy() string {
	path, err := syscall.UTF16PtrFromString(`Software\Microsoft\Windows\CurrentVersion\Internet Settings`)
	if err != nil {
		return ""
	}
	var key syscall.Handle
	if syscall.RegOpenKeyEx(syscall.HKEY_CURRENT_USER, path, 0, syscall.KEY_READ, &key) != nil {
		return ""
	}
	defer syscall.RegCloseKey(key)
	var typ, enable uint32
	n := uint32(4)
	name, _ := syscall.UTF16PtrFromString("ProxyEnable")
	if syscall.RegQueryValueEx(key, name, nil, &typ, (*byte)(unsafe.Pointer(&enable)), &n) != nil || n != 4 || enable == 0 {
		return ""
	}
	buf := make([]uint16, 2048)
	n = uint32(len(buf) * 2)
	name, _ = syscall.UTF16PtrFromString("ProxyServer")
	if syscall.RegQueryValueEx(key, name, nil, &typ, (*byte)(unsafe.Pointer(&buf[0])), &n) != nil || typ != syscall.REG_SZ {
		return ""
	}
	if int(n/2) < len(buf) {
		buf = buf[:n/2]
	}
	return syscall.UTF16ToString(buf)
}
