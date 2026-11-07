// 进入、退出阅读模式（设计稿 03 D-01）。浏览器只在用户点击时允许全屏，所以在点击的处理函数里请求。
import { go } from "../router";
import { loadPrefs } from "./prefs";

let returnTo = "";

export function openReader(id: string, anchor?: string): void {
  returnTo = window.location.hash;
  if (loadPrefs().fullscreen) enterFullscreen();
  go("read", anchor ? `${id}#${anchor}` : id);
}

export function exitReader(fallback: string): void {
  if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
  if (returnTo) {
    const target = returnTo;
    returnTo = "";
    window.location.hash = target;
  } else go("entry", fallback);
}

export function enterFullscreen(el: HTMLElement = document.documentElement): void {
  if (!document.fullscreenElement && el.requestFullscreen) void el.requestFullscreen().catch(() => undefined);
}

export function toggleFullscreen(el?: HTMLElement): void {
  if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
  else enterFullscreen(el);
}
