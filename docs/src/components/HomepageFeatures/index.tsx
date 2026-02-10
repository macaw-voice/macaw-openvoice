import type {ReactNode} from 'react';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  description: string;
};

const FeatureList: FeatureItem[] = [
  {
    title: 'Streaming STT',
    description: 'Partial and final transcripts with low TTFB and backpressure control.',
  },
  {
    title: 'Text-to-Speech',
    description: 'OpenAI-compatible speech endpoint with streaming PCM or WAV.',
  },
  {
    title: 'Full-Duplex',
    description: 'STT and TTS on the same WebSocket with mute-on-speak safety.',
  },
  {
    title: 'Session Manager',
    description: 'State machine, ring buffer, WAL, and recovery for resilient streams.',
  },
  {
    title: 'Multi-Engine',
    description: 'Faster-Whisper, WeNet, and Kokoro with a single runtime interface.',
  },
  {
    title: 'Voice Pipeline',
    description: 'Preprocessing, VAD, ITN post-processing, and metrics built in.',
  },
];

function Feature({title, description}: FeatureItem) {
  return (
    <div className={styles.featureCard}>
      <Heading as="h3" className={styles.featureTitle}>
        {title}
      </Heading>
      <p className={styles.featureDescription}>{description}</p>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className={styles.featureGrid}>
          {FeatureList.map((feature) => (
            <Feature key={feature.title} {...feature} />
          ))}
        </div>
      </div>
    </section>
  );
}
