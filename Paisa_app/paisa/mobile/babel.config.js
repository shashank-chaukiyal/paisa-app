/**
 * mobile/babel.config.js
 *
 * Fix: react-native-reanimated v3 requires its Babel plugin to be the LAST
 * plugin listed. Without this, worklets fail at runtime with
 * "ReanimatedError: Reanimated 2 failed to create a worklet".
 */
module.exports = {
  presets: ['module:@react-native/babel-preset'],
  plugins: [
    // react-native-reanimated/plugin MUST be listed last
    'react-native-reanimated/plugin',
  ],
};
