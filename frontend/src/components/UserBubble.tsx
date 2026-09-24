import styles from "./SpeechBubble.module.css";

interface UserBubbleProps {
  text: string;
}

export function UserBubble({ text }: UserBubbleProps) {
  return (
    <div className={styles.userDock} aria-hidden="true">
      <div className={`${styles.comic} ${styles.user}`}>
        <p className={styles.userLine}>{text}</p>
      </div>    </div>
  );
}
