/**
 * mobile/index.js
 *
 * React Native entry point — registers the root component.
 * Fix: This file was missing entirely, causing CI bundle step to fail
 * with "Unable to resolve module index.js".
 */
import { AppRegistry } from 'react-native';
import App from './App';
import { name as appName } from './app.json';

AppRegistry.registerComponent(appName, () => App);
