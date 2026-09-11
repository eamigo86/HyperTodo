import React,{useEffect} from 'react';
import {Keyboard,Modal,Pressable,ScrollView,StyleSheet,Text,View} from 'react-native';
import {THEME_TOKENS,useThemeName,type ThemeTokens} from '../theme';

export type RealtimeConflictDialogProps={
 message:string;update:string;goBack:string;backUnavailable:string;
 pending:boolean;canGoBack:boolean;onUpdate():void;onGoBack():void;
};

/** Controlled presentation: neither OS dismissal nor a hidden callback grants consent. */
export default function RealtimeConflictDialog(props:RealtimeConflictDialogProps){
 const styles=STYLES[useThemeName()];
 useEffect(()=>{Keyboard.dismiss();},[]);
 return <Modal visible transparent animationType="fade" onRequestClose={()=>{}}>
  <View style={styles.scrim} testID="realtime-conflict-scrim">
   <View pointerEvents="none" style={styles.dimming}/>
   <View style={styles.card} accessibilityViewIsModal testID="realtime-conflict-card">
    <ScrollView contentContainerStyle={styles.content} bounces={false}>
     <Text style={styles.message} accessibilityRole="alert" allowFontScaling>{props.message}</Text>
     <View style={styles.actions}>
      <Pressable accessibilityRole="button" accessibilityState={{disabled:props.pending,busy:props.pending}} disabled={props.pending} onPress={props.onUpdate} style={[styles.primary,props.pending&&styles.disabled]}>
       <Text style={[styles.primaryText,props.pending&&styles.disabledText]} allowFontScaling>{props.update}</Text>
      </Pressable>
      <Pressable accessibilityRole="button" accessibilityState={{disabled:props.pending||!props.canGoBack,busy:props.pending}} accessibilityHint={!props.canGoBack?props.backUnavailable:undefined} disabled={props.pending||!props.canGoBack} onPress={props.onGoBack} style={[styles.secondary,(props.pending||!props.canGoBack)&&styles.disabled]}>
       <Text style={[styles.secondaryText,(props.pending||!props.canGoBack)&&styles.disabledText]} allowFontScaling>{props.goBack}</Text>
      </Pressable>
     </View>
    </ScrollView>
   </View>
  </View>
 </Modal>;
}
const makeStyles=(t:ThemeTokens)=>StyleSheet.create({
 scrim:{flex:1,alignItems:'center',justifyContent:'center',padding:24},
 dimming:{position:'absolute',top:0,right:0,bottom:0,left:0,backgroundColor:t.scrim,opacity:0.42},
 card:{width:'100%',maxWidth:420,maxHeight:'90%',backgroundColor:t.surface,borderRadius:20,overflow:'hidden'},
 content:{padding:24},
 message:{fontSize:16,lineHeight:24,color:t.ink,marginBottom:16,flexShrink:1},
 actions:{gap:12},
 primary:{minHeight:44,minWidth:44,alignItems:'center',justifyContent:'center',backgroundColor:t.brand,borderRadius:12,padding:12},
 secondary:{minHeight:44,minWidth:44,alignItems:'center',justifyContent:'center',backgroundColor:t.chip,borderRadius:12,padding:12},
 primaryText:{fontSize:19,fontWeight:'700',color:t.on_brand,textAlign:'center',flexShrink:1},
 secondaryText:{fontSize:19,fontWeight:'700',color:t.ink,textAlign:'center',flexShrink:1},
 disabled:{backgroundColor:t.canvas,borderWidth:1,borderColor:t.ink_muted_alt},
 disabledText:{color:t.ink_label},
});
const STYLES={light:makeStyles(THEME_TOKENS.light),dark:makeStyles(THEME_TOKENS.dark)};
