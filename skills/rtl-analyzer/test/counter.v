// 测试用 Verilog 计数器
// 用于测试 rtl-analyzer 技能

module counter (
    input wire clk,
    input wire rst_n,
    input wire en,
    input wire [3:0] max_count,
    output reg [3:0] count,
    output reg overflow
);

    // 简单的计数器逻辑
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            count <= 4'd0;
            overflow <= 1'b0;
        end
        else if (en) begin
            if (count >= max_count) begin
                count <= 4'd0;
                overflow <= 1'b1;
            end
            else begin
                count <= count + 1'b1;
                overflow <= 1'b0;
            end
        end
    end

endmodule


// 带状态机的计数器（更复杂）
module counter_fsm (
    input wire clk,
    input wire rst_n,
    input wire start,
    input wire [7:0] target,
    output reg [7:0] count,
    output reg done,
    output reg [2:0] state
);

    // 状态定义
    localparam IDLE = 3'd0;
    localparam COUNTING = 3'd1;
    localparam DONE = 3'd2;

    // 状态机
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            count <= 8'd0;
            done <= 1'b0;
        end
        else begin
            case (state)
                IDLE: begin
                    if (start) begin
                        state <= COUNTING;
                        count <= 8'd0;
                        done <= 1'b0;
                    end
                end

                COUNTING: begin
                    // 嵌套 if 示例 - 会被检测为热点
                    if (count < target) begin
                        if (count < 100) begin
                            count <= count + 1'b1;
                        end
                        else if (count < 200) begin
                            count <= count + 2'd2;
                        end
                        else begin
                            count <= count + 3'd4;
                        end
                    end
                    else begin
                        state <= DONE;
                        done <= 1'b1;
                    end
                end

                DONE: begin
                    if (!start) begin
                        state <= IDLE;
                        done <= 1'b0;
                    end
                end

                default: begin
                    state <= IDLE;
                end
            endcase
        end
    end

endmodule


// 顶层模块 - 实例化多个计数器
module top_counter (
    input wire clk,
    input wire rst_n,
    input wire [1:0] sel,
    input wire start,
    input wire [7:0] target,
    output wire [7:0] out_count,
    output wire done
);

    wire [3:0] count0;
    wire [3:0] count1;
    wire overflow0, overflow1;
    wire [7:0] fsm_count;
    wire fsm_done;

    // 实例化多个计数器
    counter u_counter0 (
        .clk(clk),
        .rst_n(rst_n),
        .en(1'b1),
        .max_count(4'd10),
        .count(count0),
        .overflow(overflow0)
    );

    counter u_counter1 (
        .clk(clk),
        .rst_n(rst_n),
        .en(overflow0),
        .max_count(4'd15),
        .count(count1),
        .overflow(overflow1)
    );

    counter_fsm u_counter_fsm (
        .clk(clk),
        .rst_n(rst_n),
        .start(start),
        .target(target),
        .count(fsm_count),
        .done(fsm_done),
        .state()
    );

    // 输出选择
    assign out_count = (sel == 2'd0) ? {4'd0, count0} :
                       (sel == 2'd1) ? {4'd0, count1} :
                                       fsm_count;

    assign done = (sel == 2'd2) ? fsm_done : overflow1;

endmodule
