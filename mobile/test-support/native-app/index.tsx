import { registerRootComponent } from 'expo';
import Constants from 'expo-constants';
import { Platform } from 'react-native';
import { createNativeAppRunner } from './runner';
if (Platform.OS !== 'ios' && Platform.OS !== 'android') throw new Error('native-app-preflight:platform');
const NativeApp = createNativeAppRunner(Constants.expoConfig?.extra?.nativeApp, Platform.OS);
registerRootComponent(NativeApp);
