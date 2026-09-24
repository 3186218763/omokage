import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AssistantBubble } from "./AssistantBubble";
import { UserBubble } from "./UserBubble";
import type { ChatMessage } from "../types";

afterEach(cleanup);

const assistant: ChatMessage = {
  id: "a",
  role: "assistant",
  text: "先接住你。然后才说这句。",
  sentences: ["先接住你。", "然后才说这句。"],
  audio: [{ url: "a" }, { url: "b" }],
};

it("keeps the line she just finished while the next beat is holding", () => {
  const { rerender } = render(
    <AssistantBubble assistant={assistant} activeKey="a:0" pending={false} playing={true} holding={false} playbackComplete={false} startedIndex={0} />,
  );
  expect(screen.getByLabelText("这一轮对话").textContent).toContain("先接住你。");
  rerender(
    <AssistantBubble assistant={assistant} activeKey={null} pending={false} playing={false} holding playbackComplete={false} startedIndex={0} />,
  );
  const bubble = screen.getByLabelText("这一轮对话").textContent ?? "";
  expect(bubble).toContain("先接住你。");
  expect(bubble).not.toContain("然后才说这句。");
});

it("keeps the heard sentence through a generation/playback gap", () => {
  const { rerender } = render(
    <AssistantBubble assistant={assistant} activeKey="a:0" pending={false} playing={true} holding={false} playbackComplete={false} startedIndex={0} />,
  );
  rerender(<AssistantBubble assistant={assistant} activeKey={null} pending={false} playing={false} holding={false} playbackComplete={false} startedIndex={0} />);
  expect(screen.getByLabelText("这一轮对话").textContent).toContain("先接住你。");
  expect(screen.getByLabelText("这一轮对话").textContent).not.toContain("然后才说这句。");
  rerender(<AssistantBubble assistant={assistant} activeKey={null} pending={false} playing={false} holding={false} playbackComplete startedIndex={0} />);
  expect(screen.getByLabelText("这一轮对话").textContent).toContain("然后才说这句。");
});

it("does not show a queued sentence before its audio starts", () => {
  const { rerender } = render(
    <AssistantBubble assistant={assistant} activeKey="a:0" pending playing={false} holding={false} playbackComplete={false} startedIndex={null} />,
  );
  expect(screen.getByLabelText("这一轮对话").textContent).not.toContain("先接住你。");
  rerender(
    <AssistantBubble assistant={assistant} activeKey="a:0" pending={false} playing={true} holding={false} playbackComplete={false} startedIndex={0} />,
  );
  rerender(<AssistantBubble assistant={assistant} activeKey="a:1" pending={false} playing={false} holding={false} playbackComplete={false} startedIndex={0} />);
  expect(screen.getByLabelText("这一轮对话").textContent).toContain("先接住你。");
  rerender(<AssistantBubble assistant={assistant} activeKey="a:1" pending={false} playing={true} holding={false} playbackComplete={false} startedIndex={1} />);
  expect(screen.getByLabelText("这一轮对话").textContent).toContain("然后才说这句。");
});

it("greets with nothing to say yet", () => {
  render(<AssistantBubble assistant={null} activeKey={null} pending={false} playing={false} holding={false} playbackComplete startedIndex={null} />);
  expect(screen.getByLabelText("这一轮对话").textContent).toContain("你好，今天想聊点什么？");
});

it("shows your last line in its own bubble", () => {
  render(<UserBubble text="在吗" />);
  expect(screen.getByText("在吗")).toBeTruthy();
});
