# 通用控件样式

产品使用米白底色、黑色文字与描边、圆角按钮和荧光绿交互状态。共享变量在 `frontend/src/styles/theme.css`，按钮基础样式在 `frontend/src/styles/controls.css`。

普通操作使用 `AppButton`，支持 `secondary`（默认）、`primary`、`quiet`、`danger` 四种样式，以及 `size="small"`。按钮默认 `type="button"`；提交表单必须显式设置 `type="submit"`，避免取消、展开等操作意外提交。

```vue
<AppButton size="small" @click="copy">复制回答</AppButton>
<AppButton type="submit" variant="primary" :disabled="saving">保存修改</AppButton>
```

共享按钮自带禁用、键盘焦点和减少动画设置。图标按钮继续使用对应组件的尺寸与布局，并提供 `aria-label`。下拉选择使用已有的 `AppSelect` / `AppSelectOption`。

弹窗、划词评论与全屏写作侧栏会移动到 `body`。通用控件样式不能依赖 `#app` 祖先，否则同一按钮会在页面内正常、全屏后恢复浏览器默认外观。确认与重命名框通过 `.el-message-box` 共享主题。

基础样式为产品区域中的普通按钮提供低优先级默认外观；已有组件样式优先。编辑器工具栏、原生可编辑文档内容、下拉菜单项和 Element Plus 内部控件各用自己的样式，不套用普通操作按钮的默认间距。

浏览器回归位于 `frontend/tests-e2e/control-styling.spec.ts`，覆盖普通对话与全屏写作的复制操作、历史按钮、反馈提交、键盘焦点以及窄屏确认弹窗。
