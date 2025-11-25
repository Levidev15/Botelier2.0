import InitialNode from "./InitialNode";
import ConversationNode from "./ConversationNode";
import EndNode from "./EndNode";

export const nodeTypes = {
  initial: InitialNode,
  node: ConversationNode,
  end: EndNode,
};

export { InitialNode, ConversationNode, EndNode };
