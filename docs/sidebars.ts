import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

/**
 * Creating a sidebar enables you to:
 - create an ordered group of docs
 - render a sidebar for each doc of that group
 - provide next/previous navigation

 The sidebars can be generated from the filesystem, or explicitly defined here.

 Create as many sidebars as you want.
 */
const sidebars: SidebarsConfig = {
  docsSidebar: [
    'intro',
    {
      type: 'category',
      label: 'Getting Started',
      items: [
        'getting-started/installation',
        'getting-started/quickstart',
        'getting-started/configuration',
      ],
    },
    {
      type: 'category',
      label: 'Guides',
      items: [
        'guides/batch-transcription',
        'guides/streaming-stt',
        'guides/full-duplex',
        'guides/adding-engine',
        'guides/cli',
      ],
    },
    {
      type: 'category',
      label: 'API Reference',
      items: [
        'api-reference/rest-api',
        'api-reference/websocket-protocol',
        'api-reference/grpc-internal',
      ],
    },
    {
      type: 'category',
      label: 'Architecture',
      items: [
        'architecture/overview',
        'architecture/session-manager',
        'architecture/vad-pipeline',
        'architecture/scheduling',
      ],
    },
    {
      type: 'category',
      label: 'Community',
      items: [
        'community/contributing',
        'community/changelog',
        'community/roadmap',
      ],
    },
  ],
};

export default sidebars;
