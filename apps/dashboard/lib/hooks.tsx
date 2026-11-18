"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { api } from "./api";
import { filtersToQuery, parseFilters, toSearch } from "./filters";
import { STORY_KEY, THEME_KEY } from "./theme-script";
import type { Filters, Meta } from "./types";

// ------------------------------------------------------------ data fetching
export interface ApiState<T> {
  data: T | undefined;
  error: Error | null;
  loading: boolean;
  reload: () => void;
}

/** `key` must change whenever the request inputs change; the fetcher is read through a ref. */
export function useApi<T>(key: string, fetcher: () => Promise<T>): ApiState<T> {
  const [state, setState] = useState<{ data?: T; error: Error | null; loading: boolean }>({ error: null, loading: true });
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    fetcherRef
      .current()
      .then((data) => live && setState({ data, error: null, loading: false }))
      .catch((error: Error) => live && setState((s) => ({ data: s.data, error, loading: false })));
    return () => {
      live = false;
    };
  }, [key, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data: state.data, error: state.error, loading: state.loading, reload };
}

// ------------------------------------------------------------ URL state (global filters live in the query string)
export function useUrlState() {
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();

  const set = useCallback(
    (patch: Record<string, string | undefined | null>, opts: { push?: boolean } = {}) => {
      const next = new URLSearchParams(window.location.search);
      for (const [k, v] of Object.entries(patch)) {
        if (v === undefined || v === null || v === "") next.delete(k);
        else next.set(k, v);
      }
      const qs = next.toString();
      const url = `${pathname}${qs ? `?${qs}` : ""}`;
      if (opts.push) router.push(url, { scroll: false });
      else router.replace(url, { scroll: false });
    },
    [pathname, router],
  );

  return { params, get: (k: string) => params.get(k) ?? undefined, set, pathname };
}

export function useFilters() {
  const { params, set } = useUrlState();
  const filters: Filters = useMemo(() => parseFilters((k) => params.get(k)), [params]);
  const key = JSON.stringify(filters);
  const setFilters = useCallback(
    (patch: Partial<Record<keyof Filters, string | undefined>>) => set({ page: undefined, ...patch }),
    [set],
  );
  /** Build an in-app link that keeps the current global filters. */
  const href = useCallback(
    (path: string, extra: Record<string, string | undefined> = {}) => `${path}${toSearch({ ...filtersToQuery(filters), ...extra })}`,
    [filters],
  );
  return { filters, setFilters, href, key };
}

// ------------------------------------------------------------ meta (operators, bounds, last run)
interface MetaCtx {
  meta: Meta | undefined;
  loading: boolean;
  error: Error | null;
  reload: () => void;
}
const MetaContext = createContext<MetaCtx>({ meta: undefined, loading: true, error: null, reload: () => {} });

export function MetaProvider({ children }: { children: ReactNode }) {
  const s = useApi("meta", () => api.meta());
  const value = useMemo(() => ({ meta: s.data, loading: s.loading, error: s.error, reload: s.reload }), [s.data, s.loading, s.error, s.reload]);
  return <MetaContext.Provider value={value}>{children}</MetaContext.Provider>;
}
const noopSubscribe = () => () => {};
/** Hydrate with the server markup (no meta) even when the fetch has already finished: Suspense boundaries can hydrate late. */
export function useMeta() {
  const ctx = useContext(MetaContext);
  const hydrated = useSyncExternalStore(noopSubscribe, () => true, () => false);
  return useMemo(() => (hydrated ? ctx : { ...ctx, meta: undefined, loading: true, error: null }), [hydrated, ctx]);
}

// ------------------------------------------------------------ theme + story mode

interface UiCtx {
  theme: "light" | "dark";
  toggleTheme: () => void;
  story: boolean;
  toggleStory: () => void;
}
const UiContext = createContext<UiCtx>({ theme: "light", toggleTheme: () => {}, story: false, toggleStory: () => {} });

export function UiProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [story, setStory] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    setTheme(root.dataset.theme === "dark" ? "dark" : "light");
    setStory(root.dataset.story === "on");
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (window.localStorage.getItem(THEME_KEY)) return;
      const t = mq.matches ? "dark" : "light";
      root.dataset.theme = t;
      setTheme(t);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const toggleTheme = useCallback(() => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    window.localStorage.setItem(THEME_KEY, next);
    setTheme(next);
  }, []);

  const toggleStory = useCallback(() => {
    const on = document.documentElement.dataset.story !== "on";
    if (on) document.documentElement.dataset.story = "on";
    else delete document.documentElement.dataset.story;
    window.localStorage.setItem(STORY_KEY, on ? "1" : "0");
    setStory(on);
  }, []);

  const value = useMemo(() => ({ theme, toggleTheme, story, toggleStory }), [theme, toggleTheme, story, toggleStory]);
  return <UiContext.Provider value={value}>{children}</UiContext.Provider>;
}
export const useUi = () => useContext(UiContext);
