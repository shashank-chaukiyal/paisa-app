/**
 * mobile/babel.config.js
 *
 * Note: react-native-reanimated plugin removed.
 * Reanimated 3.10.x uses removed Java APIs in RN 0.76,
 * and 3.16.x requires RN 0.78+. Since no screens import
 * reanimated hooks, it has been removed entirely.
 */
module.exports = {
  presets: ['module:@react-native/babel-preset'],
};