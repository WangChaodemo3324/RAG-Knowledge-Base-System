export default {
  name: "TopBar",
  props: {
    info: {
      type: Object,
      required: true,
    },
  },
  template: `
    <header class="topbar">
      <div class="title">
        <h1>企业知识库问答</h1>
        <span class="status">
          <span :class="['dot', info.statusKind]"></span>
          <span>{{ info.statusText }}</span>
        </span>
      </div>
    </header>
  `,
};
