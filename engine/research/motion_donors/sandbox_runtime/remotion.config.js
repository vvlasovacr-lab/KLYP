import {Config} from '@remotion/cli/config';

// The sandbox reuses the frozen production node_modules through a junction.
// Disable the shared webpack cache so research renders cannot mutate it.
Config.overrideWebpackConfig((config) => ({...config, cache: false}));
