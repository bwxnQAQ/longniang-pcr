package main

import (
	"archive/zip"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// Windows「代理服务器」设置里那一行（比如 "127.0.0.1:7890"，或者 "http=…;https=…;socks=…"）→ 下载 https 地址该走哪个代理。
// 看不懂、没设：返回 nil（直连）。
func parseProxy(s string) *url.URL {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil
	}
	pick := s
	if strings.Contains(s, "=") {
		m := map[string]string{}
		for _, part := range strings.Split(s, ";") {
			if k, v, ok := strings.Cut(strings.TrimSpace(part), "="); ok {
				m[strings.ToLower(strings.TrimSpace(k))] = strings.TrimSpace(v)
			}
		}
		switch {
		case m["https"] != "":
			pick = m["https"]
		case m["http"] != "":
			pick = m["http"]
		case m["socks"] != "":
			v := m["socks"]
			if i := strings.Index(v, "://"); i >= 0 {
				v = v[i+3:]
			}
			pick = "socks5://" + v
		default:
			return nil
		}
	}
	if !strings.Contains(pick, "://") {
		pick = "http://" + pick
	}
	u, err := url.Parse(pick)
	if err != nil || u.Hostname() == "" {
		return nil
	}
	if h := u.Hostname(); strings.Contains(h, ":") && !strings.HasPrefix(u.Host, "[") { // 冒号一堆、又不是 [IPv6]：不是个地址
		return nil
	}
	switch u.Scheme {
	case "http", "https", "socks5", "socks5h":
		return u
	}
	return nil
}

// 下载用的客户端：环境变量里设了代理（HTTPS_PROXY 之类）就用它，没设就用 Windows 设置里的那个，都没有就直连。
func newClient(sysProxy string) *http.Client {
	sys := parseProxy(sysProxy)
	return &http.Client{Transport: &http.Transport{
		Proxy: func(r *http.Request) (*url.URL, error) {
			if u, err := http.ProxyFromEnvironment(r); err == nil && u != nil {
				return u, nil
			}
			return sys, nil
		},
		DialContext:           (&net.Dialer{Timeout: 20 * time.Second}).DialContext,
		TLSHandshakeTimeout:   20 * time.Second,
		ResponseHeaderTimeout: 40 * time.Second,
	}}
}

// 把 src 下载到 dst（先写 dst.part，下完了再改名）。连着 idle 这么久一个字节都没来，算断了。
func downloadOnce(client *http.Client, src, dst string, idle time.Duration, progress func(done, total int64)) error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	watchdog := time.AfterFunc(idle, cancel)
	defer watchdog.Stop()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, src, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", "longniang-pcr-launcher")
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("服务器回的是 %s", resp.Status)
	}
	part := dst + ".part"
	f, err := os.Create(part)
	if err != nil {
		return err
	}
	var done int64
	buf := make([]byte, 64<<10)
	for {
		watchdog.Reset(idle)
		n, rerr := resp.Body.Read(buf)
		if n > 0 {
			if _, werr := f.Write(buf[:n]); werr != nil {
				f.Close()
				os.Remove(part)
				return werr
			}
			done += int64(n)
			if progress != nil {
				progress(done, resp.ContentLength)
			}
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			f.Close()
			os.Remove(part)
			return rerr
		}
	}
	if err := f.Close(); err != nil {
		os.Remove(part)
		return err
	}
	if resp.ContentLength > 0 && done != resp.ContentLength {
		os.Remove(part)
		return fmt.Errorf("只下到 %d / %d 字节", done, resp.ContentLength)
	}
	return os.Rename(part, dst)
}

// 下载，失败了再试，一共 tries 次。
func download(con console, client *http.Client, src, dst string, tries int, idle, wait time.Duration) error {
	var err error
	for i := 1; i <= tries; i++ {
		last := int64(-1)
		err = downloadOnce(client, src, dst, idle, func(done, total int64) {
			if total > 0 {
				if pct := done * 100 / total; pct != last {
					last = pct
					con.Print(fmt.Sprintf("\r   已下载 %d%%（%.1f / %.1f MB）", pct, float64(done)/1e6, float64(total)/1e6))
				}
			} else if mb := done >> 20; mb != last {
				last = mb
				con.Print(fmt.Sprintf("\r   已下载 %d MB", mb))
			}
		})
		if last >= 0 {
			con.Say("")
		}
		if err == nil {
			return nil
		}
		if i < tries {
			con.Say(fmt.Sprintf("   第 %d 次没成（%v），再试一次……", i, err))
			time.Sleep(wait)
		}
	}
	return err
}

// 从 zip 里把 uv.exe 取出来放到 dst。
func unzipUV(zipPath, dst string) error {
	zr, err := zip.OpenReader(zipPath)
	if err != nil {
		return err
	}
	defer zr.Close()
	names := make([]string, len(zr.File))
	for i, f := range zr.File {
		names[i] = f.Name
	}
	i := pickUV(names)
	if i < 0 {
		return errors.New("压缩包里没有 uv.exe")
	}
	src, err := zr.File[i].Open()
	if err != nil {
		return err
	}
	defer src.Close()
	part := dst + ".part"
	out, err := os.OpenFile(part, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o755)
	if err != nil {
		return err
	}
	const limit = 512 << 20 // uv.exe 几十 MB；大得离谱就不对了
	n, err := io.Copy(out, io.LimitReader(src, limit+1))
	cerr := out.Close()
	if err == nil {
		err = cerr
	}
	if err == nil && n > limit {
		err = errors.New("压缩包里的 uv.exe 大得不对")
	}
	if err != nil {
		os.Remove(part)
		return err
	}
	return os.Rename(part, dst)
}

// 下载 uv 的压缩包、取出 uv.exe、删掉压缩包。
func fetchUV(con console, client *http.Client, src string, p paths) error {
	zipPath := p.uv + ".zip"
	if err := download(con, client, src, zipPath, 3, 60*time.Second, 2*time.Second); err != nil {
		return err
	}
	defer os.Remove(zipPath)
	return unzipUV(zipPath, p.uv)
}
