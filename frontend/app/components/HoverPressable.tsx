/**
 * A Pressable that also tracks hover, so buttons can show a distinct
 * hover state on web/desktop (mouse) in addition to the press state that
 * works everywhere. `onHoverIn`/`onHoverOut` are real RN Pressable props —
 * they simply never fire on a touch-only device, so this is a no-op there.
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
