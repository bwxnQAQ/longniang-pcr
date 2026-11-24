//go:build !windows

package main

// 不是 Windows 的时候用的替身：只为了能在别的系统上编译、跑自测。正式的 exe 用的是 host_windows.go。

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
)

func msgBox(text string) { fmt.Fprintln(os.Stderr, "[弹框] "+text) }

type stdConsole struct{}

func openConsole() console           { return stdConsole{} }
func (stdConsole) Print(text string) { fmt.Print(text) }
func (stdConsole) Say(line string)   { fmt.Println(line) }
func (stdConsole) Pause(prompt string) {
	fmt.Print(prompt)
	bufio.NewReader(os.Stdin).ReadString('\n')
}

func attach(cmd *exec.Cmd, con console) {
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
}

func startDetached(exe string, args []string, dir string) error {
	cmd := exec.Command(exe, args...)
	cmd.Dir = dir
	if err := cmd.Start(); err != nil {
		return err
	}
	return cmd.Process.Release()
}

func systemProxy() string { return "" }
