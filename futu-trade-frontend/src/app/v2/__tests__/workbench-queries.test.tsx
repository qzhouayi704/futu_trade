import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import V2WorkbenchPage from "../page";

const state = vi.hoisted(() => ({ options: [] as Array<{ queryKey: string[]; enabled?: boolean }> }));
vi.mock("@/lib/socket", () => ({ useSocket: () => ({ socket: null, isConnected: false }) }));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useQuery: (options: (typeof state.options)[number]) => {
    state.options.push(options);
    return { data: undefined, isError: false, isLoading: true, isFetching: false };
  },
}));
beforeEach(() => { state.options = []; });

describe("cockpit request load", () => {
  it("only enables cockpit and today's performance on first load", () => {
    renderToStaticMarkup(createElement(V2WorkbenchPage));
    expect(state.options.filter((option) => option.enabled !== false).map((option) => option.queryKey[1])).toEqual(["cockpit", "alert-performance", "alert-performance"]);
    expect(state.options.filter((option) => option.queryKey[1] === "alert-performance").map((option) => option.queryKey[3])).toEqual(["alerts", "candidates"]);
    expect(state.options.filter((option) => option.enabled === false).map((option) => option.queryKey[1])).toEqual(["candidates", "positions", "decisions", "distribution", "shadow-acceptance", "health"]);
  });
});
