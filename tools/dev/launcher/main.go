package main

import (
	"errors"
	"os"
	"os/exec"
)

func isFile(path string) bool {
	st, err := os.Stat(path)
	return err == nil && !st.IsDir()
}

// 在窗口里运行一个程序，等它结束。
func runWait(con console, exe string, args []string, dir string) int {
	cmd := exec.Command(exe, args...)
	cmd.Dir = dir
	attach(cmd, con)
	err := cmd.Run()
	if err == nil {
		return 0
	}
	var ee *exec.ExitError
	if errors.As(err, &ee) {
		return ee.ExitCode()
	}
	con.Say("   没能运行 " + exe + "：" + err.Error())
	return -1
}

// 不出声地运行（输入输出都不接）。
func runQuiet(exe string, args []string) int {
	err := exec.Command(exe, args...).Run()
	if err == nil {
		return 0
	}
	var ee *exec.ExitError
	if errors.As(err, &ee) {
		return ee.ExitCode()
	}
	return -1
}

func main() {
	exe, err := os.Executable()
	if err != nil {
		msgBox("找不到这个 exe 自己在哪：" + err.Error())
		os.Exit(1)
	}
	o := ops{
		isFile:    isFile,
		msg:       msgBox,
		console:   openConsole,
		start:     startDetached,
		run:       runWait,
		quiet:     runQuiet,
		removeAll: os.RemoveAll,
		mkdirAll:  func(p string) error { return os.MkdirAll(p, 0o755) },
		fetchUV: func(con console, p paths) error {
			return fetchUV(con, newClient(systemProxy()), uvURL, p)
		},
		setenv: func(k, v string) { _ = os.Setenv(k, v) },
	}
	os.Exit(flow(o, exe, os.Getenv("LOCALAPPDATA"), os.Args[1:]))
}
