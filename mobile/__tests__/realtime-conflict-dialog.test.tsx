import React from 'react';
import {fireEvent,render} from '@testing-library/react-native';
import {Keyboard,Modal,StyleSheet,Text} from 'react-native';
import RealtimeConflictDialog from '../src/components/RealtimeConflictDialog';
import {createThemeStore,ThemeProvider,THEME_TOKENS} from '../src/theme';

const labels={message:'This task was updated remotely.',update:'Update',goBack:'Go back',backUnavailable:'The previous screen is missing or has unsaved edits.'};
function mount(theme:'light'|'dark'='light',pending=false,canGoBack=true){
 const onUpdate=jest.fn(),onGoBack=jest.fn(),store=createThemeStore({read:()=>theme,write:()=>{}});
 const ui=render(<ThemeProvider store={store}><RealtimeConflictDialog {...labels} {...{pending,canGoBack,onUpdate,onGoBack}}/></ThemeProvider>);
 return{ui,onUpdate,onGoBack};
}
it.each(['light','dark'] as const)('shows a centered themed two-choice modal in %s and dismisses only the keyboard',theme=>{
 const dismiss=jest.spyOn(Keyboard,'dismiss').mockImplementation(()=>{}),f=mount(theme);
 try{
  expect(f.ui.UNSAFE_getByType(Modal).props).toMatchObject({visible:true,transparent:true});
  expect(f.ui.getByTestId('realtime-conflict-scrim')).toHaveStyle({flex:1,justifyContent:'center',alignItems:'center'});
  expect(f.ui.getByTestId('realtime-conflict-card')).toHaveStyle({backgroundColor:THEME_TOKENS[theme].surface,borderRadius:20});
  expect(f.ui.getByTestId('realtime-conflict-card').props.accessibilityViewIsModal).toBe(true);
  expect(f.ui.getAllByRole('button')).toHaveLength(2);expect(f.ui.getByText(labels.message).props.allowFontScaling).toBe(true);
  expect(f.ui.UNSAFE_getAllByType(Text)).toHaveLength(3);expect(f.ui.getByRole('alert').props.children).toBe(labels.message);
  fireEvent.press(f.ui.getByRole('button',{name:'Update'}));fireEvent.press(f.ui.getByRole('button',{name:'Go back'}));
  expect(f.onUpdate).toHaveBeenCalledTimes(1);expect(f.onGoBack).toHaveBeenCalledTimes(1);expect(dismiss).toHaveBeenCalledTimes(1);
  f.ui.UNSAFE_getByType(Modal).props.onRequestClose();
  expect(f.onUpdate).toHaveBeenCalledTimes(1);expect(f.onGoBack).toHaveBeenCalledTimes(1);
 }finally{f.ui.unmount();dismiss.mockRestore();}
});
it('disables both choices while an operation is in flight without adding a cancel button',()=>{
 const f=mount('light',true);
 try{for(const button of f.ui.getAllByRole('button')){expect(button).toBeDisabled();fireEvent.press(button);}expect(f.onUpdate).not.toHaveBeenCalled();expect(f.onGoBack).not.toHaveBeenCalled();}finally{f.ui.unmount();}
});
it('keeps Go back visible but unavailable when it cannot protect the destination',()=>{
 const f=mount('light',false,false);
 try{expect(f.ui.queryByText(labels.backUnavailable)).toBeNull();expect(f.ui.getByRole('button',{name:'Go back'}).props.accessibilityHint).toBe(labels.backUnavailable);expect(f.ui.getByRole('button',{name:'Go back'})).toBeDisabled();expect(f.ui.getByRole('button',{name:'Update'})).not.toBeDisabled();expect(f.ui.UNSAFE_getAllByType(Text)).toHaveLength(3);fireEvent.press(f.ui.getByRole('button',{name:'Go back'}));expect(f.onGoBack).not.toHaveBeenCalled();}finally{f.ui.unmount();}
});

it.each(['light','dark'] as const)('visibly distinguishes unavailable and pending choices with readable %s tokens',theme=>{
 const f=mount(theme,false,false),t=THEME_TOKENS[theme];
 const luminance=(hex:string)=>hex.slice(1).match(/../g)!.map(value=>parseInt(value,16)/255).map(value=>value<=0.04045?value/12.92:((value+0.055)/1.055)**2.4).reduce((sum,value,index)=>sum+value*[0.2126,0.7152,0.0722][index],0);
 const verify=(name:string)=>{
  const button=f.ui.getByRole('button',{name}),background=StyleSheet.flatten(button.props.style).backgroundColor;
  expect(button).toBeDisabled();expect(button).toHaveStyle({backgroundColor:t.canvas,borderWidth:1,borderColor:t.ink_muted_alt});
  const text=f.ui.getByText(name);expect(text).toHaveStyle({color:t.ink_label});
  const foreground=StyleSheet.flatten(text.props.style).color,a=luminance(foreground),b=luminance(background);
  expect((Math.max(a,b)+0.05)/(Math.min(a,b)+0.05)).toBeGreaterThanOrEqual(4.5);
 };
 try{
  expect(f.ui.getByRole('button',{name:'Update'})).toHaveStyle({backgroundColor:t.brand});verify('Go back');
  f.ui.rerender(<ThemeProvider store={createThemeStore({read:()=>theme,write:()=>{}})}><RealtimeConflictDialog {...labels} pending canGoBack onUpdate={f.onUpdate} onGoBack={f.onGoBack}/></ThemeProvider>);
  verify('Update');verify('Go back');
  for(const button of f.ui.getAllByRole('button'))fireEvent.press(button);expect(f.onUpdate).not.toHaveBeenCalled();expect(f.onGoBack).not.toHaveBeenCalled();
 }finally{f.ui.unmount();}
});
