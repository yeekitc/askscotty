/**
 * A Pressable that also tracks hover, for a distinct mouse state on web and
 * desktop. `onHoverIn`/`onHoverOut` are real RN props that simply never fire on
 * a touch-only device, so this costs nothing there.
 */

import { useState } from 'react'
import { Pressable, type PressableProps, type StyleProp, type ViewStyle } from 'react-native'

type RenderState = { pressed: boolean; hovered: boolean }

type Props = Omit<PressableProps, 'style' | 'children'> & {
  style?: StyleProp<ViewStyle> | ((state: RenderState) => StyleProp<ViewStyle>)
  children?: React.ReactNode | ((state: RenderState) => React.ReactNode)
}

export function HoverPressable({ style, children, onHoverIn, onHoverOut, ...props }: Props) {
  const [hovered, setHovered] = useState(false)

  return (
    <Pressable
      {...props}
      onHoverIn={(e) => {
        setHovered(true)
        onHoverIn?.(e)
      }}
      onHoverOut={(e) => {
        setHovered(false)
        onHoverOut?.(e)
      }}
      style={({ pressed }) => (typeof style === 'function' ? style({ pressed, hovered }) : style)}
    >
      {typeof children === 'function' ? ({ pressed }: { pressed: boolean }) => children({ pressed, hovered }) : children}
    </Pressable>
  )
}
