import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { mountStage, type PerformanceInput, type StageController } from "../live2d/stage";
import styles from "./Live2DStage.module.css";

export interface Live2DHandle {
  setMouth(value: number): void;
  setPerformance(input: PerformanceInput): void;
  playMotion(name: string): void;
  resetIdle(): void;
}

interface Live2DStageProps {
  onClick?: () => void;
}

export const Live2DStage = forwardRef<Live2DHandle, Live2DStageProps>(
  function Live2DStage({ onClick }, ref) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const controllerRef = useRef<StageController | null>(null);
  const pendingRef = useRef<PerformanceInput>({
    emotion: "日常",
    intensity: 0.55,
    decayMs: 0,
  });
  const mouthRef = useRef(0);
  const [ready, setReady] = useState(false);
  const [backgroundUrl, setBackgroundUrl] = useState<string | null>(null);

  useImperativeHandle(ref, () => ({
    setMouth(value: number) {
      mouthRef.current = value;
      controllerRef.current?.setMouth(value);
    },
    setPerformance(input: PerformanceInput) {
      pendingRef.current = input;
      controllerRef.current?.setPerformance(input);
    },
    playMotion(name: string) {
      controllerRef.current?.playMotion(name);
    },
    resetIdle() {
      pendingRef.current = { emotion: "日常", intensity: 0.55, decayMs: 0 };
      mouthRef.current = 0;
      controllerRef.current?.resetIdle();
    },
  }), []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let cancelled = false;
    let controller: StageController | null = null;

    void (async () => {
      const response = await fetch("/api/live2d");
      if (!response.ok || cancelled) return;
      const manifest = (await response.json()) as {
        model_url?: string;
        core_url?: string;
        background_url?: string | null;
      };
      if (cancelled) return;
      if (manifest.background_url) setBackgroundUrl(manifest.background_url);
      if (!manifest.model_url || !manifest.core_url) return;
      try {
        controller = await mountStage(host, {
          model_url: manifest.model_url,
          core_url: manifest.core_url,
        });
      } catch (error) {
        console.error("Live2D 舞台加载失败", error);
        return;
      }
      if (cancelled) {
        controller.destroy();
        return;
      }
      controller.setMouth(mouthRef.current);
      controller.setPerformance(pendingRef.current);
      controllerRef.current = controller;
      setReady(true);
    })();

    return () => {
      cancelled = true;
      controller?.destroy();
      controllerRef.current = null;
    };
  }, []);

  return (
    <div className={styles.wrap} onClick={onClick}>
      {backgroundUrl ? (
        <div
          className={styles.backdrop}
          style={{ backgroundImage: `url("${backgroundUrl}")` }}
          aria-hidden="true"
        />
      ) : null}
      <div className={styles.host} ref={hostRef} />
      <div className={`${styles.fallback} ${ready ? styles.hidden : ""}`} aria-hidden="true">
        菜
      </div>
    </div>
  );
});
